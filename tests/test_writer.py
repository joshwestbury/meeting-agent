from datetime import datetime
from pathlib import Path

import yaml

from meeting_agent.note_schema import NotePayload
from meeting_agent.writer import (
    RenderContext,
    build_note_filename,
    render_markdown_note,
    sanitize_title_for_filename,
    write_note_atomic,
)


def _payload(**overrides: object) -> NotePayload:
    base = {
        "title": "Weekly Sync",
        "meeting_date": "2026-03-01",
        "attendees": ["Alex", "Jamie"],
        "client": "Acme",
        "project": "Pilot",
        "tags": ["meeting", "client/acme"],
        "folder_choice": "Work/Meetings/Clients/Acme/",
        "summary": "Discussed milestones and blockers.",
        "action_items": ["Send proposal"],
        "key_details": ["Budget reviewed"],
        "decisions": [],
        "open_questions": [],
        "sensitive": False,
    }
    base.update(overrides)
    return NotePayload.model_validate(base)


def test_sanitize_title_for_filename_removes_invalid_chars() -> None:
    assert sanitize_title_for_filename('  Q1 Sync: Acme/Delta?  ') == "Q1 Sync Acme Delta"


def test_build_note_filename_primary_and_time_fallback() -> None:
    primary = build_note_filename(meeting_date="2026-03-01", title="Weekly Sync")
    fallback = build_note_filename(
        meeting_date="2026-03-01",
        title="Weekly Sync",
        started_at="2026-03-01T09:12:00-06:00",
        use_time_fallback=True,
    )
    assert primary == "2026-03-01 - Weekly Sync.md"
    assert fallback == "2026-03-01 0912 - Weekly Sync.md"


def test_render_markdown_note_includes_required_frontmatter_and_sections() -> None:
    note = _payload()
    rendered = render_markdown_note(
        note,
        RenderContext(
            source_url="https://notes.granola.ai/t/abc",
            granola_id="g-123",
            transcript_hash="hash-xyz",
            created=datetime(2026, 3, 1, 9, 12, 0),
            vault_folder="Work/Meetings/Clients/Acme/",
        ),
    )

    parts = rendered.split("---\n")
    assert len(parts) >= 3
    frontmatter_raw = parts[1]
    frontmatter = yaml.safe_load(frontmatter_raw)
    assert frontmatter["type"] == "meeting"
    assert frontmatter["source"] == "granola"
    assert frontmatter["source_url"] == "https://notes.granola.ai/t/abc"
    assert frontmatter["meeting_date"] == "2026-03-01"
    assert frontmatter["granola_id"] == "g-123"
    assert frontmatter["transcript_hash"] == "hash-xyz"
    assert frontmatter["vault_folder"] == "Work/Meetings/Clients/Acme/"

    assert "## Summary" in rendered
    assert "## Action Items" in rendered
    assert "## Key Details" in rendered
    assert "Transcript Source: https://notes.granola.ai/t/abc" in rendered


def test_render_markdown_note_omits_optional_empty_sections() -> None:
    note = _payload(decisions=[], open_questions=[])
    rendered = render_markdown_note(
        note,
        RenderContext(
            source_url="https://notes.granola.ai/t/abc",
            granola_id="",
            transcript_hash="hash-xyz",
            created=datetime(2026, 3, 1, 9, 12, 0),
            vault_folder="Inbox/Meetings/",
        ),
    )
    assert "## Decisions" not in rendered
    assert "## Open Questions" not in rendered


def test_write_note_atomic_writes_content(tmp_path: Path) -> None:
    output = tmp_path / "notes" / "2026-03-01 - Weekly Sync.md"
    markdown = "# Note\n"
    written = write_note_atomic(output, markdown)
    assert written == output
    assert output.read_text(encoding="utf-8") == markdown
