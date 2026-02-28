import json
from pathlib import Path

import pytest

from meeting_agent.errors import StateError
from meeting_agent.state import (
    StateEntry,
    evaluate_idempotency,
    load_state,
    save_state,
    state_lock,
    upsert_state_entry,
)


def _entry(
    *,
    granola_id: str = "",
    transcript_hash: str = "hash-1",
    source_key: str = "key-1",
    status: str = "processed",
) -> StateEntry:
    return StateEntry(
        granola_id=granola_id,
        transcript_hash=transcript_hash,
        source_key=source_key,
        source_url="https://notes.granola.ai/t/id",
        transcript_path="/tmp/t.txt",
        last_processed_at="2026-02-28T10:00:00-06:00",
        output_path="/vault/out.md",
        status=status,  # type: ignore[arg-type]
    )


def test_save_and_load_state_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    entries = [_entry(granola_id="g1", transcript_hash="h1"), _entry(granola_id="g2", transcript_hash="h2")]
    save_state(entries, path)
    loaded = load_state(path)
    assert loaded == entries


def test_load_state_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert load_state(tmp_path / "missing.json") == []


def test_load_state_rejects_invalid_json_shape(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"not":"a-list"}', encoding="utf-8")
    with pytest.raises(StateError, match="JSON array"):
        load_state(path)


def test_load_state_rejects_invalid_status(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            [
                {
                    "granola_id": "",
                    "transcript_hash": "h",
                    "source_key": "k",
                    "source_url": "",
                    "transcript_path": "",
                    "last_processed_at": "now",
                    "output_path": "",
                    "status": "bad",
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(StateError, match="Invalid state status"):
        load_state(path)


def test_evaluate_idempotency_update_by_granola_id() -> None:
    entries = [_entry(granola_id="g1", transcript_hash="h1")]
    decision = evaluate_idempotency(entries, granola_id="g1", transcript_hash="new-hash")
    assert decision.action == "update"
    assert decision.reason == "matching_granola_id"


def test_evaluate_idempotency_skip_by_hash() -> None:
    entries = [_entry(granola_id="g1", transcript_hash="h1")]
    decision = evaluate_idempotency(entries, granola_id="g2", transcript_hash="h1")
    assert decision.action == "skip"
    assert decision.reason == "matching_transcript_hash"


def test_evaluate_idempotency_collision_without_granola_id() -> None:
    entries = [_entry(granola_id="", transcript_hash="h1")]
    decision = evaluate_idempotency(entries, granola_id="", transcript_hash="h2")
    assert decision.action == "collision"


def test_upsert_state_entry_updates_existing_by_granola_id() -> None:
    entries = [_entry(granola_id="g1", transcript_hash="h1")]
    updated = upsert_state_entry(entries, _entry(granola_id="g1", transcript_hash="h2", source_key="k2"))
    assert len(updated) == 1
    assert updated[0].transcript_hash == "h2"


def test_upsert_state_entry_updates_existing_by_hash() -> None:
    entries = [_entry(granola_id="", transcript_hash="h1")]
    updated = upsert_state_entry(entries, _entry(granola_id="", transcript_hash="h1", source_key="k2"))
    assert len(updated) == 1
    assert updated[0].source_key == "k2"


def test_upsert_state_entry_appends_new_entry() -> None:
    entries = [_entry(granola_id="g1", transcript_hash="h1")]
    updated = upsert_state_entry(entries, _entry(granola_id="g2", transcript_hash="h2"))
    assert len(updated) == 2


def test_state_lock_prevents_concurrent_acquisition(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    with state_lock(state_path, timeout_seconds=0.05):
        with pytest.raises(StateError, match="Could not acquire state lock"):
            with state_lock(state_path, timeout_seconds=0.05):
                pass


def test_save_state_is_atomic_on_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text('[{"existing":true}]\n', encoding="utf-8")

    original_replace = Path.replace

    def _raise_replace(self: Path, target: Path) -> Path:
        if self.name.endswith(".tmp") and target == state_path:
            raise OSError("replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", _raise_replace, raising=True)

    with pytest.raises(OSError, match="replace failed"):
        save_state([_entry()], state_path)

    assert state_path.read_text(encoding="utf-8") == '[{"existing":true}]\n'
