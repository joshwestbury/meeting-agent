import json
from pathlib import Path

import pytest

from meeting_agent.logging import get_log_path, log_event


def test_get_log_path_uses_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert get_log_path() == tmp_path / ".config" / "meeting-agent" / "meetings.log"


def test_log_event_writes_jsonl_record(tmp_path: Path) -> None:
    log_path = tmp_path / "meetings.log"
    ok = log_event(
        command="process",
        source_key="k1",
        source_url="https://notes.granola.ai/t/abc",
        transcript_path="/tmp/t.txt",
        action="retrieval_success",
        folder_choice="Inbox/Meetings/",
        folder_reason="no_llm",
        output_path="/vault/Inbox/Meetings/2026-03-01 - A.md",
        path=log_path,
    )
    assert ok is True
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[-1])
    assert payload["command"] == "process"
    assert payload["action"] == "retrieval_success"
    assert payload["folder_choice"] == "Inbox/Meetings/"
    assert payload["source_key"] == "k1"


def test_log_event_returns_false_on_write_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise OSError("nope")

    monkeypatch.setattr("meeting_agent.logging._append_jsonl", _raise)
    assert log_event(command="process", action="start") is False
