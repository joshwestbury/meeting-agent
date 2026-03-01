from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
from typing import Any


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def write_quarantine_artifact(
    staging_root: Path,
    *,
    source_url: str,
    meeting_id: str,
    transcript_hash: str,
    source_key: str,
    attempted_folder: str,
    attempted_output_path: str,
    error: str,
    raw_payload: dict[str, Any] | None = None,
) -> Path:
    failed_root = staging_root / "failed-notes"
    failed_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_meeting_id = _sanitize_name(meeting_id)
    artifact_path = failed_root / f"{timestamp}-{safe_meeting_id}.json"

    payload: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "meeting_id": meeting_id,
        "transcript_hash": transcript_hash,
        "source_key": source_key,
        "attempted_folder": attempted_folder,
        "attempted_output_path": attempted_output_path,
        "error": error,
    }
    if raw_payload is not None:
        payload["raw_payload"] = raw_payload

    _atomic_write_text(artifact_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return artifact_path


def best_effort_quarantine_artifact(
    staging_root: Path,
    *,
    source_url: str,
    meeting_id: str,
    transcript_hash: str,
    source_key: str,
    attempted_folder: str,
    attempted_output_path: str,
    error: str,
    raw_payload: dict[str, Any] | None = None,
) -> Path | None:
    try:
        return write_quarantine_artifact(
            staging_root,
            source_url=source_url,
            meeting_id=meeting_id,
            transcript_hash=transcript_hash,
            source_key=source_key,
            attempted_folder=attempted_folder,
            attempted_output_path=attempted_output_path,
            error=error,
            raw_payload=raw_payload,
        )
    except OSError:
        return None


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
