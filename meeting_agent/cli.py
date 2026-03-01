from pathlib import Path

import typer

from meeting_agent import models
from meeting_agent.config import (
    AppConfig,
    load_and_validate_startup_config,
    save_config,
    validate_init_config,
)
from meeting_agent.errors import ConfigError, RetrievalError
from meeting_agent.auth import import_desktop_session_credentials
from meeting_agent.retrieval import retrieve_transcript

app = typer.Typer(help="Meeting Agent CLI")
models_app = typer.Typer(help="Local model management commands")
app.add_typer(models_app, name="models")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Entry point for meeting-agent CLI."""
    if ctx.invoked_subcommand in {"init", "auth-import"}:
        return

    try:
        load_and_validate_startup_config()
    except ConfigError as exc:
        typer.echo(
            f"Configuration error: {exc}\nRun `meeting-agent init` to create/update config."
        )
        raise typer.Exit(code=2) from exc

    if ctx.invoked_subcommand is None:
        typer.echo("Interactive flow is not implemented yet. Use `meeting-agent init` first.")


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
        typer.echo(f"Config validation failed: {exc}")
        raise typer.Exit(code=2) from exc

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
        typer.echo(f"Granola auth-check failed [{exc.code}]: {exc}")
        raise typer.Exit(code=2) from exc

    typer.echo("Granola auth-check succeeded.")
    typer.echo(f"meeting_id: {result.meeting_id}")
    typer.echo(f"transcript_chars: {len(result.transcript_text)}")


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
