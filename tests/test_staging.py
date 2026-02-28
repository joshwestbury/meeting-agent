import json
from pathlib import Path

from meeting_agent.staging import ensure_staging_layout, stage_retrieval_cache, stage_transcript


def test_ensure_staging_layout_creates_directories(tmp_path: Path) -> None:
    layout = ensure_staging_layout(tmp_path / "staging")
    assert layout["transcripts"].is_dir()
    assert layout["failed_notes"].is_dir()
    assert layout["retrieval_cache"].is_dir()


def test_stage_transcript_writes_normalized_file(tmp_path: Path) -> None:
    path = stage_transcript(
        tmp_path / "staging",
        "29250e01-0751-4e02-9b24-f6d06f878b04",
        "line1\r\n\r\n\r\nline2  \n",
    )

    assert path.exists()
    assert path.read_text(encoding="utf-8") == "line1\n\nline2"


def test_stage_transcript_sanitizes_meeting_id(tmp_path: Path) -> None:
    path = stage_transcript(tmp_path / "staging", "../unsafe name", "hello")
    assert path.name == "unsafe-name.txt"


def test_stage_retrieval_cache_writes_json_when_enabled(tmp_path: Path) -> None:
    payload = {"a": 1, "z": "value"}
    path = stage_retrieval_cache(tmp_path / "staging", "meeting/1", payload, enabled=True)

    assert path is not None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == payload


def test_stage_retrieval_cache_returns_none_when_disabled(tmp_path: Path) -> None:
    path = stage_retrieval_cache(tmp_path / "staging", "meeting-1", {"x": 1}, enabled=False)
    assert path is None
