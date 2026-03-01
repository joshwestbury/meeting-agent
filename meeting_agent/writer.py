from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import tempfile

import yaml

from meeting_agent.note_schema import NotePayload


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_SPACE_RUN_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class RenderContext:
    source_url: str
    granola_id: str
    transcript_hash: str
    created: datetime
    vault_folder: str
    needs_review: bool = False


def sanitize_title_for_filename(title: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub(" ", title.strip())
    cleaned = _SPACE_RUN_RE.sub(" ", cleaned).strip(" .")
    return cleaned or "Meeting Notes"


def build_note_filename(
    *,
    meeting_date: str,
    title: str,
    started_at: str | None = None,
    use_time_fallback: bool = False,
) -> str:
    safe_title = sanitize_title_for_filename(title)
    if not use_time_fallback:
        return f"{meeting_date} - {safe_title}.md"

    stamp = _extract_time_stamp(started_at)
    return f"{meeting_date} {stamp} - {safe_title}.md"


def render_markdown_note(
    payload: NotePayload,
    context: RenderContext,
    *,
    include_full_transcript: bool = False,
    transcript_text: str | None = None,
) -> str:
    frontmatter = {
        "type": "meeting",
        "source": "granola",
        "source_url": context.source_url,
        "meeting_date": payload.meeting_date,
        "attendees": payload.attendees,
        "client": payload.client,
        "project": payload.project,
        "tags": payload.tags or ["meeting"],
        "granola_id": context.granola_id,
        "transcript_hash": context.transcript_hash,
        "created": context.created.isoformat(),
        "needs_review": context.needs_review,
        "sensitive": payload.sensitive,
        "vault_folder": context.vault_folder,
    }
    fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False).strip()
    sections = [
        "## Summary",
        payload.summary,
        "",
        "## Action Items",
        _render_list_or_none(payload.action_items),
        "",
        "## Key Details",
        _render_list_or_none(payload.key_details),
    ]

    if payload.decisions:
        sections.extend(["", "## Decisions", _render_list_or_none(payload.decisions)])
    if payload.open_questions:
        sections.extend(["", "## Open Questions", _render_list_or_none(payload.open_questions)])

    sections.extend(["", f"Transcript Source: {context.source_url}"])
    if include_full_transcript and transcript_text is not None:
        sections.extend(["", "## Full Transcript", transcript_text.strip() or "_(empty transcript)_"])
    body = "\n".join(sections).strip() + "\n"
    return f"---\n{fm}\n---\n\n{body}"


def write_note_atomic(output_path: Path, markdown: str) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=output_path.parent,
        prefix=f"{output_path.name}.",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(markdown)
        tmp_name = tmp.name
    Path(tmp_name).replace(output_path)
    return output_path


def _render_list_or_none(items: list[str] | None) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)


def _extract_time_stamp(started_at: str | None) -> str:
    if not started_at:
        return "0000"
    candidate = started_at.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return "0000"
    return parsed.strftime("%H%M")
