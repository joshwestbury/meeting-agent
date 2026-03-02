from pathlib import Path
import subprocess
from datetime import date, datetime
from dataclasses import dataclass
import shutil
import time
from urllib.parse import urlparse

import httpx
import typer

from meeting_agent import models
from meeting_agent.auth import import_desktop_session_credentials
from meeting_agent.config import (
    AppConfig,
    load_and_validate_startup_config,
    save_config,
    validate_init_config,
)
from meeting_agent.errors import (
    CollisionError,
    ConfigError,
    FolderValidationError,
    RetrievalError,
    SchemaValidationError,
    StateError,
)
from meeting_agent.exit_codes import exit_code_for_error, render_error_message
from meeting_agent.llm import (
    build_no_llm_payload,
    generate_note_payload_with_local_runtime,
)
from meeting_agent.logging import log_event
from meeting_agent.normalize import compute_source_key, compute_transcript_hash, normalize_transcript_text
from meeting_agent.pipeline import process_note_write, resolve_output_path
from meeting_agent.retrieval import retrieve_transcript
from meeting_agent.staging import stage_transcript
from meeting_agent.state import StateEntry, load_state
from meeting_agent.writer import RenderContext, build_note_filename

app = typer.Typer(help="Meeting Agent CLI")
models_app = typer.Typer(help="Local model management commands")
app.add_typer(models_app, name="models")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Entry point for meeting-agent CLI."""
    if ctx.invoked_subcommand in {"init", "auth-import"}:
        return

    try:
        config = load_and_validate_startup_config()
    except ConfigError as exc:
        typer.echo(render_error_message(exc, context="Configuration error"))
        typer.echo("Run `meeting-agent init` to create/update config.")
        raise typer.Exit(code=exit_code_for_error(exc)) from exc

    if ctx.invoked_subcommand is None:
        _interactive_default_flow(config)


@app.command("init")
def init_command() -> None:
    """Initialize meeting-agent configuration."""
    default_vault_root = "~/Documents/Alter Mentis Obsidian Vault"
    default_staging_root = "~/granola-export"
    default_timezone = "local"

    vault_root = typer.prompt("Vault root", default=default_vault_root)
    staging_root = typer.prompt("Staging root", default=default_staging_root)
    default_folder_raw = typer.prompt("Default vault-relative folder", default="", show_default=False)
    timezone = typer.prompt("Timezone", default=default_timezone)
    auth_mode = typer.prompt(
        "Auth mode (token/cookie/manual_export/desktop_session)",
        default="manual_export",
    )
    auth_mode = auth_mode.strip()
    if auth_mode not in {"token", "cookie", "manual_export", "desktop_session"}:
        typer.echo("Auth mode must be one of: token, cookie, manual_export, desktop_session")
        raise typer.Exit(code=2)

    auth_token_env: str | None = None
    cookie_file: str | None = None
    if auth_mode == "token":
        auth_token_env = typer.prompt("Token environment variable name", default="MEETING_AGENT_TOKEN")
    elif auth_mode == "cookie":
        cookie_file = typer.prompt(
            "Cookie file path",
            default="~/.config/meeting-agent/cookies.txt",
        )

    config = AppConfig(
        vault_root=vault_root,
        staging_root=staging_root,
        default_folder=default_folder_raw or None,
        timezone=timezone,
        auth_mode=auth_mode,
        auth_token_env=auth_token_env,
        cookie_file=cookie_file,
    )

    try:
        validate_init_config(config)
    except ConfigError as exc:
        typer.echo(render_error_message(exc, context="Config validation failed"))
        raise typer.Exit(code=exit_code_for_error(exc)) from exc

    path = save_config(config)
    typer.echo(f"Config written: {path}")
    typer.echo("Startup validation passed.")


@app.command("auth-import")
def auth_import_command(
    session_path: str | None = typer.Option(
        None,
        "--session-path",
        help="Path to Granola desktop session credential file.",
    )
) -> None:
    """Import Granola desktop-session credentials into keychain storage."""
    source_path = Path(session_path).expanduser() if session_path else None
    creds = import_desktop_session_credentials(source_path)
    typer.echo("Desktop-session credentials imported.")
    typer.echo(f"client_id: {creds.client_id}")
    typer.echo(f"has_access_token: {bool(creds.access_token)}")


@app.command("auth-check")
def auth_check_command(granola_link: str) -> None:
    """Validate real Granola connectivity/auth using a meeting link."""
    config = load_and_validate_startup_config()
    if config.auth_mode == "manual_export":
        typer.echo(
            "auth-check requires remote auth mode (`token`, `cookie`, or `desktop_session`). "
            "Current config is `manual_export`."
        )
        raise typer.Exit(code=2)

    typer.echo("Checking Granola connectivity...")
    try:
        result = retrieve_transcript(granola_link, config, max_retries=0)
    except RetrievalError as exc:
        typer.echo(render_error_message(exc, context="Granola auth-check failed"))
        raise typer.Exit(code=exit_code_for_error(exc)) from exc

    typer.echo("Granola auth-check succeeded.")
    typer.echo(f"meeting_id: {result.meeting_id}")
    typer.echo(f"transcript_chars: {len(result.transcript_text)}")


@app.command("process")
def process_command(
    granola_link: str | None = typer.Argument(
        None,
        help="Granola meeting link (required unless --new is used).",
    ),
    folder: str | None = typer.Option(None, "--folder", help="Vault-relative folder destination."),
    yes: bool = typer.Option(False, "--yes", help="Skip write confirmation prompt."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show resolved output, do not write/state update."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Bypass LLM and use deterministic template."),
    summary: bool = typer.Option(False, "--summary", help="Write summary note format (default behavior)."),
    full: bool = typer.Option(False, "--full", help="Include full transcript body in note."),
    process_new: bool = typer.Option(False, "--new", help="Process unprocessed/changed staged transcripts."),
) -> None:
    """Process one meeting link through retrieval, generation, and write pipeline."""
    config = load_and_validate_startup_config()
    if summary and full:
        typer.echo("Use either --summary or --full, not both.")
        raise typer.Exit(code=3)
    output_mode = "full" if full else "summary"

    if process_new:
        folder_choice = _resolve_folder_choice(config, folder)
        exit_code = _run_batch_process_new(
            config=config,
            folder_choice=folder_choice,
            no_llm=no_llm,
            dry_run=dry_run,
            output_mode=output_mode,
            command_name="process_new",
        )
        if exit_code != 0:
            raise typer.Exit(code=exit_code)
        return

    if not granola_link:
        typer.echo("A Granola link is required unless --new is used.")
        raise typer.Exit(code=3)

    folder_choice = _resolve_folder_choice(config, folder)
    exit_code = _run_single_process(
        config=config,
        granola_link=granola_link,
        folder_choice=folder_choice,
        confirm_write=not yes,
        dry_run=dry_run,
        no_llm=no_llm,
        output_mode=output_mode,
        command_name="process",
    )
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


@app.command("open")
def open_command(
    latest: bool = typer.Option(False, "--latest", help="Open the latest successfully written note.")
) -> None:
    """Open the latest processed note from state."""
    if not latest:
        typer.echo("Only `meeting-agent open --latest` is supported.")
        raise typer.Exit(code=3)

    entries = load_state()
    candidate = _select_latest_processed(entries)
    if candidate is None:
        typer.echo("No processed notes found in state.")
        raise typer.Exit(code=21)

    output_path = Path(candidate.output_path)
    if not output_path.exists():
        typer.echo(f"Latest note path no longer exists: {output_path}")
        raise typer.Exit(code=21)

    try:
        subprocess.run(["open", str(output_path)], check=True)
    except (OSError, subprocess.CalledProcessError):
        typer.echo(f"Unable to open note automatically. Path: {output_path}")
        raise typer.Exit(code=23)

    typer.echo(f"Opened: {output_path}")


@models_app.command("pull")
def models_pull_command(
    model: str | None = typer.Option(
        None,
        "--model",
        help="Model repo id (for example LiquidAI/LFM2-2.6B-Transcript-GGUF).",
    ),
    variant: str | None = typer.Option(None, "--variant", help="Model quantization variant."),
    force: bool = typer.Option(False, "--force", help="Redownload even if file exists."),
) -> None:
    """Download configured local model into cache."""
    config = load_and_validate_startup_config()
    repo_id = model or config.llm_model
    resolved_variant = variant or config.llm_model_variant
    cache_dir = config.model_cache_dir
    guidance = models.model_size_guidance(repo_id)

    typer.echo(f"Pulling model: {repo_id} ({resolved_variant})")
    typer.echo(f"Cache directory: {cache_dir}")
    typer.echo(f"Disk guidance: {guidance}")

    result = models.pull_model(
        repo_id=repo_id,
        variant=resolved_variant,
        model_cache_dir=cache_dir,
        force=force,
    )
    if result.downloaded:
        typer.echo(f"Downloaded: {result.output_path}")
    else:
        typer.echo(f"Already present: {result.output_path}")


@models_app.command("doctor")
def models_doctor_command(
    model: str | None = typer.Option(None, "--model", help="Model repo id override."),
    variant: str | None = typer.Option(None, "--variant", help="Model variant override."),
) -> None:
    """Validate local runtime, downloaded model presence, and server reachability."""
    config = load_and_validate_startup_config()
    repo_id = model or config.llm_model
    resolved_variant = variant or config.llm_model_variant

    report = models.run_models_doctor(
        model_cache_dir=config.model_cache_dir,
        repo_id=repo_id,
        variant=resolved_variant,
        server_url=config.llm_server_url,
    )

    typer.echo("Model doctor report:")
    typer.echo(f"- runtime_installed: {report.runtime_installed}")
    if report.runtime_path:
        typer.echo(f"- runtime_path: {report.runtime_path}")
    typer.echo(f"- model_present: {report.model_present}")
    typer.echo(f"- model_path: {report.model_path}")
    typer.echo(f"- server_reachable: {report.server_reachable}")

    if not report.runtime_installed:
        typer.echo("Action: install llama.cpp and ensure `llama-server` is on PATH.")
    if not report.model_present:
        typer.echo("Action: run `meeting-agent models pull` to download the configured model.")
    if not report.server_reachable:
        typer.echo("Action: start local server at configured llm_server_url.")


@models_app.command("list")
def models_list_command() -> None:
    """List installed local GGUF models and active config target."""
    config = load_and_validate_startup_config()
    installed = models.list_installed_models(config.model_cache_dir)

    typer.echo(f"Active model: {config.llm_model} ({config.llm_model_variant})")
    typer.echo(f"Model cache: {config.model_cache_dir}")
    if not installed:
        typer.echo("Installed models: none")
        return

    typer.echo("Installed models:")
    for path in installed:
        typer.echo(f"- {path}")


def _interactive_default_flow(config: AppConfig) -> None:
    granola_link = typer.prompt("Granola meeting link")
    folder_choice = _resolve_folder_choice(config, None, prompt_label="Destination folder (vault-relative)")
    exit_code = _run_single_process(
        config=config,
        granola_link=granola_link,
        folder_choice=folder_choice,
        confirm_write=True,
        dry_run=False,
        no_llm=False,
        output_mode="summary",
        command_name="interactive",
    )
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _resolve_folder_choice(
    config: AppConfig,
    folder: str | None,
    *,
    prompt_label: str = "Destination folder (vault-relative)",
) -> str:
    if folder and folder.strip():
        return folder.strip()
    if config.default_folder and config.default_folder.strip():
        return config.default_folder.strip()
    return typer.prompt(prompt_label)


def _run_single_process(
    *,
    config: AppConfig,
    granola_link: str,
    folder_choice: str,
    confirm_write: bool,
    dry_run: bool,
    no_llm: bool,
    output_mode: str,
    command_name: str,
) -> int:
    log_event(command=command_name, source_url=granola_link, action="start")
    typer.echo("Retrieving transcript...")

    try:
        retrieval = retrieve_transcript(granola_link, config)
    except RetrievalError as exc:
        log_event(
            command=command_name,
            source_url=granola_link,
            action="retrieval_failure",
            error=f"[{exc.code}] {exc}",
        )
        typer.echo(render_error_message(exc, context="Retrieval failed"))
        return exit_code_for_error(exc)

    normalized_text = normalize_transcript_text(retrieval.transcript_text)
    transcript_hash = compute_transcript_hash(normalized_text)
    identity_granola_id = (retrieval.granola_id or "").strip() or retrieval.meeting_id
    source_key = compute_source_key(identity_granola_id, normalized_text)
    transcript_path = stage_transcript(config.staging_root, retrieval.meeting_id, normalized_text, normalize=False)
    log_event(
        command=command_name,
        source_key=source_key,
        source_url=granola_link,
        transcript_path=str(transcript_path),
        action="retrieval_success",
    )

    meeting_date = _resolve_meeting_date(retrieval.started_at)
    title = (retrieval.title or "Meeting Notes").strip() or "Meeting Notes"

    try:
        if no_llm or config.llm_mode == "none":
            reason = "no_llm"
            payload = build_no_llm_payload(
                meeting_date=meeting_date,
                title=title,
                folder_choice=folder_choice,
                tags=["meeting"],
            )
        else:
            reason = "llm"
            _ensure_local_llm_server(config)
            payload = generate_note_payload_with_local_runtime(
                normalized_text,
                [folder_choice],
                model=config.llm_model,
                server_url=config.llm_server_url,
            )
    except SchemaValidationError as exc:
        log_event(
            command=command_name,
            source_key=source_key,
            source_url=granola_link,
            transcript_path=str(transcript_path),
            action="schema_validation_failure",
            folder_choice=folder_choice,
            error=str(exc),
        )
        typer.echo(render_error_message(exc, context="Schema validation failed"))
        return exit_code_for_error(exc)

    # Recording metadata is authoritative: always use the call's recorded date.
    payload = payload.model_copy(update={"meeting_date": meeting_date})

    filename = build_note_filename(
        meeting_date=payload.meeting_date,
        title=payload.title,
        started_at=retrieval.started_at,
    )
    try:
        output_path = resolve_output_path(config.vault_root, payload.folder_choice, filename)
    except FolderValidationError as exc:
        log_event(
            command=command_name,
            source_key=source_key,
            source_url=granola_link,
            transcript_path=str(transcript_path),
            action="write_failure",
            folder_choice=payload.folder_choice,
            folder_reason=reason,
            error=str(exc),
        )
        typer.echo(render_error_message(exc, context="Folder validation failed"))
        return exit_code_for_error(exc)

    if dry_run:
        typer.echo("Dry run preview:")
        typer.echo(f"title: {payload.title}")
        typer.echo(f"meeting_date: {payload.meeting_date}")
        typer.echo(f"folder: {payload.folder_choice}")
        typer.echo(f"filename: {filename}")
        typer.echo(f"output_path: {output_path}")
        log_event(
            command=command_name,
            source_key=source_key,
            source_url=granola_link,
            transcript_path=str(transcript_path),
            action="dry_run",
            folder_choice=payload.folder_choice,
            folder_reason=reason,
            output_path=str(output_path),
        )
        return 0

    if confirm_write:
        typer.echo("Preview:")
        typer.echo(f"- Meeting title: {payload.title}")
        typer.echo(f"- Meeting date: {payload.meeting_date}")
        typer.echo(f"- Target folder: {payload.folder_choice}")
        typer.echo(f"- Filename: {filename}")
        typer.echo(f"- Output path: {output_path}")
        if not typer.confirm("Write note?", default=False):
            log_event(
                command=command_name,
                source_key=source_key,
                source_url=granola_link,
                transcript_path=str(transcript_path),
                action="aborted_by_user",
                folder_choice=payload.folder_choice,
                folder_reason=reason,
                output_path=str(output_path),
            )
            typer.echo("Aborted. No note written.")
            return 0

    render_context = RenderContext(
        source_url=granola_link,
        granola_id=identity_granola_id,
        transcript_hash=transcript_hash,
        created=datetime.now().astimezone(),
        vault_folder=payload.folder_choice,
        needs_review=False,
    )

    try:
        result = process_note_write(
            config=config,
            payload=payload,
            render_context=render_context,
            source_url=granola_link,
            meeting_id=retrieval.meeting_id,
            granola_id=identity_granola_id,
            transcript_hash=transcript_hash,
            source_key=source_key,
            transcript_path=transcript_path,
            transcript_text=normalized_text,
            include_full_transcript=(output_mode == "full"),
            started_at=retrieval.started_at,
            raw_payload=retrieval.raw_payload,
        )
    except (CollisionError, StateError, FolderValidationError) as exc:
        log_event(
            command=command_name,
            source_key=source_key,
            source_url=granola_link,
            transcript_path=str(transcript_path),
            action="write_failure",
            folder_choice=payload.folder_choice,
            folder_reason=reason,
            output_path=str(output_path),
            error=str(exc),
        )
        typer.echo(render_error_message(exc, context="Write failed"))
        return exit_code_for_error(exc)

    log_event(
        command=command_name,
        source_key=source_key,
        source_url=granola_link,
        transcript_path=str(transcript_path),
        action=f"write_{result.status}",
        folder_choice=payload.folder_choice,
        folder_reason=reason,
        output_path=str(result.output_path or ""),
        error="" if result.status != "quarantined" else f"quarantine:{result.quarantine_path}",
    )
    if result.status == "processed":
        typer.echo(f"Note written: {result.output_path}")
        return 0
    if result.status == "skipped":
        typer.echo(f"Skipped duplicate transcript. Existing note: {result.output_path}")
        return 0
    typer.echo(f"Quarantined due to collision. Artifact: {result.quarantine_path}")
    return 6


def _resolve_meeting_date(started_at: str | None) -> str:
    if not started_at:
        return date.today().isoformat()
    candidate = started_at.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return date.today().isoformat()
    return parsed.date().isoformat()


def _select_latest_processed(entries: list[StateEntry]) -> StateEntry | None:
    processed = [entry for entry in entries if entry.status == "processed" and entry.output_path]
    if not processed:
        return None
    return max(processed, key=lambda entry: _parse_ts(entry.last_processed_at))


def _parse_ts(value: str) -> datetime:
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return datetime.min


@dataclass(frozen=True)
class _BatchCounters:
    processed: int = 0
    updated: int = 0
    skipped: int = 0
    quarantined: int = 0
    failed: int = 0

    def bump(self, field: str) -> "_BatchCounters":
        values = {
            "processed": self.processed,
            "updated": self.updated,
            "skipped": self.skipped,
            "quarantined": self.quarantined,
            "failed": self.failed,
        }
        values[field] += 1
        return _BatchCounters(**values)


def _run_batch_process_new(
    *,
    config: AppConfig,
    folder_choice: str,
    no_llm: bool,
    dry_run: bool,
    output_mode: str,
    command_name: str,
) -> int:
    transcripts_dir = config.staging_root / "transcripts"
    staged_files = sorted(transcripts_dir.glob("*.txt"))
    if not staged_files:
        typer.echo(f"No staged transcripts found at {transcripts_dir}")
        return 0

    counters = _BatchCounters()
    for transcript_file in staged_files:
        try:
            normalized = normalize_transcript_text(transcript_file.read_text(encoding="utf-8"))
        except OSError as exc:
            counters = counters.bump("failed")
            typer.echo(render_error_message(exc, context=f"[failed] {transcript_file.name}"))
            log_event(
                command=command_name,
                transcript_path=str(transcript_file),
                source_url=f"staged://{transcript_file.stem}",
                action="read_failure",
                error=str(exc),
            )
            continue

        transcript_hash = compute_transcript_hash(normalized)
        if _batch_should_skip(config, transcript_file, transcript_hash):
            counters = counters.bump("skipped")
            continue

        meeting_id = transcript_file.stem
        source_url = f"staged://{meeting_id}"
        identity_granola_id = meeting_id
        source_key = compute_source_key(identity_granola_id, normalized)
        title = _title_from_meeting_id(meeting_id)

        try:
            if dry_run:
                payload = build_no_llm_payload(
                    meeting_date=date.today().isoformat(),
                    title=title,
                    folder_choice=folder_choice,
                    tags=["meeting", "staged"],
                )
            elif no_llm or config.llm_mode == "none":
                payload = build_no_llm_payload(
                    meeting_date=date.today().isoformat(),
                    title=title,
                    folder_choice=folder_choice,
                    tags=["meeting", "staged"],
                )
            else:
                _ensure_local_llm_server(config)
                payload = generate_note_payload_with_local_runtime(
                    normalized,
                    [folder_choice],
                    model=config.llm_model,
                    server_url=config.llm_server_url,
                )
        except SchemaValidationError as exc:
            counters = counters.bump("failed")
            typer.echo(
                render_error_message(exc, context=f"[failed] {transcript_file.name} schema validation failed")
            )
            log_event(
                command=command_name,
                source_key=source_key,
                source_url=source_url,
                transcript_path=str(transcript_file),
                action="schema_validation_failure",
                folder_choice=folder_choice,
                error=str(exc),
            )
            continue

        if dry_run:
            preview_filename = build_note_filename(meeting_date=payload.meeting_date, title=payload.title)
            preview_output = resolve_output_path(config.vault_root, folder_choice, preview_filename)
            typer.echo(f"[dry-run] {transcript_file.name} -> {preview_output}")
            counters = counters.bump("processed")
            continue

        try:
            result = process_note_write(
                config=config,
                payload=payload,
                render_context=RenderContext(
                    source_url=source_url,
                    granola_id=identity_granola_id,
                    transcript_hash=transcript_hash,
                    created=datetime.now().astimezone(),
                    vault_folder=folder_choice,
                    needs_review=False,
                ),
                source_url=source_url,
                meeting_id=meeting_id,
                granola_id=identity_granola_id,
                transcript_hash=transcript_hash,
                source_key=source_key,
                transcript_path=transcript_file,
                transcript_text=normalized,
                include_full_transcript=(output_mode == "full"),
                raw_payload={"source": "staged_transcript"},
            )
        except (CollisionError, FolderValidationError, StateError) as exc:
            counters = counters.bump("failed")
            typer.echo(render_error_message(exc, context=f"[failed] {transcript_file.name}"))
            log_event(
                command=command_name,
                source_key=source_key,
                source_url=source_url,
                transcript_path=str(transcript_file),
                action="write_failure",
                folder_choice=folder_choice,
                output_path="",
                error=str(exc),
            )
            continue

        if result.status == "processed":
            if result.decision_reason == "matching_granola_id":
                counters = counters.bump("updated")
            else:
                counters = counters.bump("processed")
        elif result.status == "skipped":
            counters = counters.bump("skipped")
        elif result.status == "quarantined":
            counters = counters.bump("quarantined")
        else:
            counters = counters.bump("failed")

    typer.echo("Batch summary:")
    typer.echo(f"- processed: {counters.processed}")
    typer.echo(f"- updated: {counters.updated}")
    typer.echo(f"- skipped: {counters.skipped}")
    typer.echo(f"- quarantined: {counters.quarantined}")
    typer.echo(f"- failed: {counters.failed}")

    return 1 if counters.failed > 0 else 0


def _batch_should_skip(config: AppConfig, transcript_file: Path, transcript_hash: str) -> bool:
    entries = load_state()
    file_path = str(transcript_file)
    for entry in entries:
        if entry.transcript_path == file_path:
            return entry.transcript_hash == transcript_hash
    return any(entry.transcript_hash == transcript_hash for entry in entries)


def _title_from_meeting_id(meeting_id: str) -> str:
    cleaned = meeting_id.replace("-", " ").strip()
    return cleaned if cleaned else "Meeting Notes"


def _ensure_local_llm_server(config: AppConfig) -> None:
    if _is_server_reachable(config.llm_server_url):
        return

    runtime_path = shutil.which("llama-server")
    if not runtime_path:
        raise SchemaValidationError(
            "Local LLM runtime `llama-server` was not found on PATH. Install llama.cpp first."
        )

    filename = models.resolve_model_filename(config.llm_model, config.llm_model_variant)
    model_path = models.resolve_model_output_path(config.model_cache_dir, config.llm_model, filename)
    if not model_path.exists():
        raise SchemaValidationError(
            f"Configured model not found at {model_path}. Run `meeting-agent models pull`."
        )

    parsed = urlparse(config.llm_server_url)
    if parsed.scheme not in {"http", ""}:
        raise SchemaValidationError(f"Unsupported llm_server_url scheme: {config.llm_server_url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8080

    try:
        subprocess.Popen(
            [
                runtime_path,
                "-m",
                str(model_path),
                "--host",
                host,
                "--port",
                str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise SchemaValidationError(f"Could not start local LLM server: {exc}") from exc

    if not _wait_for_server(config.llm_server_url, timeout_seconds=45.0):
        raise SchemaValidationError(
            f"Local LLM server did not become ready at {config.llm_server_url}. Start it manually and retry."
        )


def _is_server_reachable(server_url: str) -> bool:
    endpoint = f"{server_url.rstrip('/')}/v1/models"
    try:
        response = httpx.get(endpoint, timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code < 400


def _wait_for_server(server_url: str, *, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _is_server_reachable(server_url):
            return True
        time.sleep(0.25)
    return False
