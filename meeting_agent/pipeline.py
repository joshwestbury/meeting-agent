from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from meeting_agent.config import AppConfig
from meeting_agent.errors import CollisionError, FolderValidationError
from meeting_agent.note_schema import NotePayload
from meeting_agent.quarantine import best_effort_quarantine_artifact
from meeting_agent.routing import resolve_vault_folder
from meeting_agent.state import (
    IdempotencyDecision,
    StateEntry,
    evaluate_idempotency,
    load_state,
    save_state,
    state_lock,
    upsert_state_entry,
)
from meeting_agent.writer import RenderContext, build_note_filename, render_markdown_note, write_note_atomic


@dataclass(frozen=True)
class PipelineResult:
    status: str
    output_path: Path | None
    quarantine_path: Path | None
    decision_reason: str


def resolve_output_path(vault_root: Path, folder_input: str, filename: str) -> Path:
    if "/" in filename or "\\" in filename:
        raise FolderValidationError("Filename must not include path separators")
    folder = resolve_vault_folder(vault_root, folder_input, create=True)
    output = (folder / filename).resolve()
    root = vault_root.resolve()
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise FolderValidationError("Resolved output path escapes vault root") from exc
    return output


def process_note_write(
    *,
    config: AppConfig,
    payload: NotePayload,
    render_context: RenderContext,
    source_url: str,
    meeting_id: str,
    granola_id: str,
    transcript_hash: str,
    source_key: str,
    transcript_path: Path,
    started_at: str | None = None,
    state_path: Path | None = None,
    raw_payload: dict | None = None,
) -> PipelineResult:
    filename = build_note_filename(
        meeting_date=payload.meeting_date,
        title=payload.title,
        started_at=started_at,
        use_time_fallback=False,
    )
    intended_output = resolve_output_path(config.vault_root, payload.folder_choice, filename)

    with state_lock(state_path):
        entries = load_state(state_path)
        decision = evaluate_idempotency(
            entries,
            granola_id=granola_id,
            transcript_hash=transcript_hash,
        )

        if decision.action == "skip":
            return PipelineResult(
                status="skipped",
                output_path=Path(decision.existing_entry.output_path) if decision.existing_entry else None,
                quarantine_path=None,
                decision_reason=decision.reason,
            )

        if decision.action == "collision":
            quarantine_path = _write_collision_quarantine(
                config=config,
                source_url=source_url,
                meeting_id=meeting_id,
                transcript_hash=transcript_hash,
                source_key=source_key,
                folder_choice=payload.folder_choice,
                intended_output=intended_output,
                error_message="Collision policy triggered (missing granola_id and new transcript hash).",
                raw_payload=raw_payload,
            )
            quarantined_entry = _state_entry(
                granola_id=granola_id,
                transcript_hash=transcript_hash,
                source_key=source_key,
                source_url=source_url,
                transcript_path=transcript_path,
                output_path=intended_output if intended_output else None,
                status="quarantined",
            )
            save_state(upsert_state_entry(entries, quarantined_entry), state_path)
            return PipelineResult(
                status="quarantined",
                output_path=None,
                quarantine_path=quarantine_path,
                decision_reason=decision.reason,
            )

        output_path = _choose_output_path_for_write(
            config=config,
            payload=payload,
            decision=decision,
            intended_output=intended_output,
            started_at=started_at,
        )
        markdown = render_markdown_note(payload, render_context)

        try:
            write_note_atomic(output_path, markdown)
        except OSError as exc:
            quarantine_path = _write_collision_quarantine(
                config=config,
                source_url=source_url,
                meeting_id=meeting_id,
                transcript_hash=transcript_hash,
                source_key=source_key,
                folder_choice=payload.folder_choice,
                intended_output=output_path,
                error_message=f"Write failed: {exc}",
                raw_payload=raw_payload,
            )
            raise CollisionError(f"Could not write note: {output_path}") from exc

        processed_entry = _state_entry(
            granola_id=granola_id,
            transcript_hash=transcript_hash,
            source_key=source_key,
            source_url=source_url,
            transcript_path=transcript_path,
            output_path=output_path,
            status="processed",
        )
        save_state(upsert_state_entry(entries, processed_entry), state_path)
        return PipelineResult(
            status="processed",
            output_path=output_path,
            quarantine_path=None,
            decision_reason=decision.reason,
        )


def _choose_output_path_for_write(
    *,
    config: AppConfig,
    payload: NotePayload,
    decision: IdempotencyDecision,
    intended_output: Path,
    started_at: str | None,
) -> Path:
    if decision.action == "update" and decision.existing_entry and decision.existing_entry.output_path:
        return Path(decision.existing_entry.output_path)

    if not intended_output.exists():
        return intended_output

    alt_filename = build_note_filename(
        meeting_date=payload.meeting_date,
        title=payload.title,
        started_at=started_at,
        use_time_fallback=True,
    )
    alt_output = resolve_output_path(config.vault_root, payload.folder_choice, alt_filename)
    if alt_output.exists():
        raise CollisionError(f"Collision detected for output path: {intended_output}")
    return alt_output


def _write_collision_quarantine(
    *,
    config: AppConfig,
    source_url: str,
    meeting_id: str,
    transcript_hash: str,
    source_key: str,
    folder_choice: str,
    intended_output: Path | None,
    error_message: str,
    raw_payload: dict | None,
) -> Path | None:
    return best_effort_quarantine_artifact(
        config.staging_root,
        source_url=source_url,
        meeting_id=meeting_id,
        transcript_hash=transcript_hash,
        source_key=source_key,
        attempted_folder=folder_choice,
        attempted_output_path=str(intended_output) if intended_output else "",
        error=error_message,
        raw_payload=raw_payload,
    )


def _state_entry(
    *,
    granola_id: str,
    transcript_hash: str,
    source_key: str,
    source_url: str,
    transcript_path: Path,
    output_path: Path | None,
    status: str,
) -> StateEntry:
    return StateEntry(
        granola_id=granola_id,
        transcript_hash=transcript_hash,
        source_key=source_key,
        source_url=source_url,
        transcript_path=str(transcript_path),
        last_processed_at=datetime.now().astimezone().isoformat(),
        output_path=str(output_path) if output_path else "",
        status=status,  # type: ignore[arg-type]
    )
