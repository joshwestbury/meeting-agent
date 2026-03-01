from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any


def get_log_path() -> Path:
    return Path.home() / ".config" / "meeting-agent" / "meetings.log"


def log_event(
    *,
    command: str,
    source_key: str = "",
    source_url: str = "",
    transcript_path: str = "",
    action: str,
    folder_choice: str = "",
    folder_reason: str = "",
    output_path: str = "",
    error: str = "",
    path: Path | None = None,
) -> bool:
    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "source_key": source_key,
        "source_url": source_url,
        "transcript_path": transcript_path,
        "action": action,
        "folder_choice": folder_choice,
        "folder_reason": folder_reason,
        "output_path": output_path,
        "error": error,
    }

    log_path = path or get_log_path()
    try:
        _append_jsonl(log_path, record)
    except OSError:
        return False
    return True


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        if path.exists():
            tmp.write(path.read_text(encoding="utf-8"))
        tmp.write(line)
        tmp_name = tmp.name
    Path(tmp_name).replace(path)
