from datetime import datetime
import json
from pathlib import Path

import pytest

from meeting_agent.config import AppConfig
from meeting_agent.errors import CollisionError
from meeting_agent.note_schema import NotePayload
from meeting_agent.pipeline import process_note_write
from meeting_agent.state import StateEntry, load_state, save_state
from meeting_agent.writer import RenderContext


def _config(tmp_path: Path) -> AppConfig:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    return AppConfig(
        vault_root=vault_root,
        staging_root=tmp_path / "staging",
        auth_mode="manual_export",
        llm_mode="none",
    )


def _payload(**overrides: object) -> NotePayload:
    base = {
        "title": "Weekly Sync",
        "meeting_date": "2026-03-01",
        "attendees": [],
        "client": "",
        "project": "",
        "tags": ["meeting"],
        "folder_choice": "Inbox/Meetings/",
        "summary": "Summary",
        "action_items": ["A1"],
        "key_details": ["K1"],
        "decisions": [],
        "open_questions": [],
        "sensitive": False,
    }
    base.update(overrides)
    return NotePayload.model_validate(base)


def _render_ctx(folder: str = "Inbox/Meetings/") -> RenderContext:
    return RenderContext(
        source_url="https://notes.granola.ai/t/abc",
        granola_id="",
        transcript_hash="hash1",
        created=datetime(2026, 3, 1, 10, 0, 0),
        vault_folder=folder,
    )


def _state_entry(**overrides: object) -> StateEntry:
    base: dict[str, object] = {
        "granola_id": "",
        "transcript_hash": "hash-old",
        "source_key": "key-old",
        "source_url": "https://notes.granola.ai/t/old",
        "transcript_path": "/tmp/t.txt",
        "last_processed_at": "2026-03-01T10:00:00-06:00",
        "output_path": "/tmp/out.md",
        "status": "processed",
    }
    base.update(overrides)
    return StateEntry(**base)  # type: ignore[arg-type]


def test_process_note_write_new_entry_writes_note_and_state(tmp_path: Path) -> None:
    config = _config(tmp_path)
    state_path = tmp_path / "state.json"

    result = process_note_write(
        config=config,
        payload=_payload(),
        render_context=_render_ctx(),
        source_url="https://notes.granola.ai/t/abc",
        meeting_id="abc",
        granola_id="g1",
        transcript_hash="hash1",
        source_key="g1",
        transcript_path=tmp_path / "staging" / "transcripts" / "abc.txt",
        state_path=state_path,
    )

    assert result.status == "processed"
    assert result.output_path is not None
    assert result.output_path.exists()
    entries = load_state(state_path)
    assert len(entries) == 1
    assert entries[0].granola_id == "g1"
    assert entries[0].status == "processed"


def test_process_note_write_update_in_place_uses_existing_output_path(tmp_path: Path) -> None:
    config = _config(tmp_path)
    state_path = tmp_path / "state.json"
    existing_path = config.vault_root / "Inbox" / "Meetings" / "existing.md"
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text("old", encoding="utf-8")
    save_state([_state_entry(granola_id="g1", output_path=str(existing_path))], state_path)

    result = process_note_write(
        config=config,
        payload=_payload(),
        render_context=_render_ctx(),
        source_url="https://notes.granola.ai/t/new",
        meeting_id="new",
        granola_id="g1",
        transcript_hash="hash-new",
        source_key="g1",
        transcript_path=tmp_path / "staging" / "transcripts" / "new.txt",
        state_path=state_path,
    )
    assert result.status == "processed"
    assert result.output_path == existing_path
    assert "## Summary" in existing_path.read_text(encoding="utf-8")


def test_process_note_write_skip_on_matching_hash(tmp_path: Path) -> None:
    config = _config(tmp_path)
    state_path = tmp_path / "state.json"
    existing_path = config.vault_root / "Inbox" / "Meetings" / "old.md"
    save_state([_state_entry(transcript_hash="hash1", output_path=str(existing_path))], state_path)

    result = process_note_write(
        config=config,
        payload=_payload(),
        render_context=_render_ctx(),
        source_url="https://notes.granola.ai/t/abc",
        meeting_id="abc",
        granola_id="",
        transcript_hash="hash1",
        source_key="hash1",
        transcript_path=tmp_path / "staging" / "transcripts" / "abc.txt",
        state_path=state_path,
    )
    assert result.status == "skipped"
    assert result.output_path == existing_path


def test_process_note_write_collision_quarantines_and_updates_state(tmp_path: Path) -> None:
    config = _config(tmp_path)
    state_path = tmp_path / "state.json"
    save_state([_state_entry(granola_id="", transcript_hash="hash-old")], state_path)

    result = process_note_write(
        config=config,
        payload=_payload(),
        render_context=_render_ctx(),
        source_url="https://notes.granola.ai/t/new",
        meeting_id="new",
        granola_id="",
        transcript_hash="hash-new",
        source_key="hash-new",
        transcript_path=tmp_path / "staging" / "transcripts" / "new.txt",
        state_path=state_path,
        raw_payload={"id": 1},
    )
    assert result.status == "quarantined"
    assert result.quarantine_path is not None
    assert result.quarantine_path.exists()
    data = json.loads(result.quarantine_path.read_text(encoding="utf-8"))
    assert data["meeting_id"] == "new"

    entries = load_state(state_path)
    assert any(entry.status == "quarantined" and entry.transcript_hash == "hash-new" for entry in entries)


def test_process_note_write_failure_quarantines_and_does_not_mark_processed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    state_path = tmp_path / "state.json"

    def _raise_write(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr("meeting_agent.pipeline.write_note_atomic", _raise_write)

    with pytest.raises(CollisionError, match="Could not write note"):
        process_note_write(
            config=config,
            payload=_payload(),
            render_context=_render_ctx(),
            source_url="https://notes.granola.ai/t/new",
            meeting_id="new",
            granola_id="g-new",
            transcript_hash="hash-new",
            source_key="g-new",
            transcript_path=tmp_path / "staging" / "transcripts" / "new.txt",
            state_path=state_path,
            raw_payload={"id": 2},
        )

    entries = load_state(state_path)
    assert entries == []
    failed_notes = list((config.staging_root / "failed-notes").glob("*.json"))
    assert failed_notes
