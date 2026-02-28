from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Literal

from meeting_agent.errors import StateError


StateStatus = Literal["processed", "quarantined", "skipped"]
IdempotencyAction = Literal["new", "update", "skip", "collision"]


@dataclass
class StateEntry:
    granola_id: str
    transcript_hash: str
    source_key: str
    source_url: str
    transcript_path: str
    last_processed_at: str
    output_path: str
    status: StateStatus


@dataclass
class IdempotencyDecision:
    action: IdempotencyAction
    existing_entry: StateEntry | None
    reason: str


def get_state_path() -> Path:
    return Path.home() / ".config" / "meeting-agent" / "state.json"


def load_state(path: Path | None = None) -> list[StateEntry]:
    state_path = path or get_state_path()
    if not state_path.exists():
        return []
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"Could not read state file: {state_path}") from exc

    if not isinstance(raw, list):
        raise StateError("State file must contain a JSON array")

    entries: list[StateEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            raise StateError("State entry must be an object")
        try:
            entries.append(
                StateEntry(
                    granola_id=str(item.get("granola_id", "")),
                    transcript_hash=str(item["transcript_hash"]),
                    source_key=str(item["source_key"]),
                    source_url=str(item.get("source_url", "")),
                    transcript_path=str(item.get("transcript_path", "")),
                    last_processed_at=str(item["last_processed_at"]),
                    output_path=str(item.get("output_path", "")),
                    status=_validate_status(str(item["status"])),
                )
            )
        except KeyError as exc:
            raise StateError(f"State entry missing required key: {exc.args[0]}") from exc
    return entries


def save_state(entries: list[StateEntry], path: Path | None = None) -> Path:
    state_path = path or get_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(entry) for entry in entries]

    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=state_path.parent,
        prefix=f"{state_path.name}.",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        json.dump(payload, tmp, indent=2)
        tmp.write("\n")
        tmp_name = tmp.name
    Path(tmp_name).replace(state_path)
    return state_path


def evaluate_idempotency(
    entries: list[StateEntry],
    *,
    granola_id: str,
    transcript_hash: str,
) -> IdempotencyDecision:
    for entry in entries:
        if granola_id and entry.granola_id and entry.granola_id == granola_id:
            return IdempotencyDecision("update", entry, "matching_granola_id")

    for entry in entries:
        if entry.transcript_hash == transcript_hash:
            return IdempotencyDecision("skip", entry, "matching_transcript_hash")

    if granola_id:
        return IdempotencyDecision("new", None, "no_matching_identity")
    return IdempotencyDecision("collision", None, "missing_granola_id_and_new_hash")


def upsert_state_entry(entries: list[StateEntry], new_entry: StateEntry) -> list[StateEntry]:
    updated = list(entries)
    for idx, entry in enumerate(updated):
        if new_entry.granola_id and entry.granola_id == new_entry.granola_id:
            updated[idx] = new_entry
            return updated
        if entry.transcript_hash == new_entry.transcript_hash:
            updated[idx] = new_entry
            return updated
    updated.append(new_entry)
    return updated


@contextmanager
def state_lock(path: Path | None = None, *, timeout_seconds: float = 2.0):
    state_path = path or get_state_path()
    lock_path = state_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if (time.monotonic() - start) >= timeout_seconds:
                raise StateError(f"Could not acquire state lock: {lock_path}")
            time.sleep(0.02)

    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
        yield lock_path
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            lock_path.unlink(missing_ok=True)
        except OSError as exc:
            raise StateError(f"Could not release state lock: {lock_path}") from exc


def _validate_status(value: str) -> StateStatus:
    if value not in {"processed", "quarantined", "skipped"}:
        raise StateError(f"Invalid state status: {value}")
    return value  # type: ignore[return-value]
