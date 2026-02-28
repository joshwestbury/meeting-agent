import json
from pathlib import Path
import re
import tempfile
from typing import Any

from meeting_agent.normalize import normalize_transcript_text


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_staging_layout(staging_root: Path) -> dict[str, Path]:
    transcripts = staging_root / "transcripts"
    failed_notes = staging_root / "failed-notes"
    retrieval_cache = staging_root / "retrieval-cache"

    transcripts.mkdir(parents=True, exist_ok=True)
    failed_notes.mkdir(parents=True, exist_ok=True)
    retrieval_cache.mkdir(parents=True, exist_ok=True)

    return {
        "root": staging_root,
        "transcripts": transcripts,
        "failed_notes": failed_notes,
        "retrieval_cache": retrieval_cache,
    }


def stage_transcript(
    staging_root: Path,
    meeting_id: str,
    transcript_text: str,
    *,
    normalize: bool = True,
) -> Path:
    layout = ensure_staging_layout(staging_root)
    safe_meeting_id = _sanitize_name(meeting_id)
    transcript_path = layout["transcripts"] / f"{safe_meeting_id}.txt"
    output_text = normalize_transcript_text(transcript_text) if normalize else transcript_text
    _atomic_write_text(transcript_path, output_text)
    return transcript_path


def stage_retrieval_cache(
    staging_root: Path,
    meeting_id: str,
    payload: dict[str, Any],
    *,
    enabled: bool,
) -> Path | None:
    if not enabled:
        return None
    layout = ensure_staging_layout(staging_root)
    safe_meeting_id = _sanitize_name(meeting_id)
    cache_path = layout["retrieval_cache"] / f"{safe_meeting_id}.json"
    _atomic_write_text(cache_path, json.dumps(payload, indent=2, sort_keys=True))
    return cache_path


def _sanitize_name(value: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("-", value.strip())
    cleaned = cleaned.strip("-.")
    return cleaned or "unknown-meeting"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(content)
        tmp_name = tmp.name
    Path(tmp_name).replace(path)
