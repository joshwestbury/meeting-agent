import json
from pathlib import Path

import pytest

from meeting_agent.quarantine import best_effort_quarantine_artifact, write_quarantine_artifact


def test_write_quarantine_artifact_writes_expected_payload(tmp_path: Path) -> None:
    path = write_quarantine_artifact(
        tmp_path,
        source_url="https://notes.granola.ai/t/abc",
        meeting_id="abc",
        transcript_hash="hash1",
        source_key="key1",
        attempted_folder="Inbox/Meetings/",
        attempted_output_path="/vault/Inbox/Meetings/2026-03-01 - Test.md",
        error="failed validation",
        raw_payload={"raw": True},
    )
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["source_url"] == "https://notes.granola.ai/t/abc"
    assert data["meeting_id"] == "abc"
    assert data["transcript_hash"] == "hash1"
    assert data["source_key"] == "key1"
    assert data["attempted_folder"] == "Inbox/Meetings/"
    assert data["raw_payload"] == {"raw": True}


def test_best_effort_quarantine_artifact_returns_none_on_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("meeting_agent.quarantine.write_quarantine_artifact", _raise)
    result = best_effort_quarantine_artifact(
        tmp_path,
        source_url="u",
        meeting_id="m",
        transcript_hash="h",
        source_key="k",
        attempted_folder="f",
        attempted_output_path="o",
        error="e",
    )
    assert result is None
