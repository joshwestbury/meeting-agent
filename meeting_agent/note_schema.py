import json
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from meeting_agent.errors import SchemaValidationError


MAX_SECTION_CHARS = 20_000
MAX_TOTAL_NOTE_CHARS = 60_000


class NotePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    meeting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    attendees: list[str] = Field(default_factory=list)
    client: str = ""
    project: str = ""
    tags: list[str] = Field(default_factory=lambda: ["meeting"])
    folder_choice: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=MAX_SECTION_CHARS)
    action_items: list[str] = Field(default_factory=list)
    key_details: list[str] = Field(default_factory=list)
    decisions: list[str] | None = None
    open_questions: list[str] | None = None
    sensitive: bool = False

    @field_validator("title", "meeting_date", "client", "project", "folder_choice", "summary")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("attendees", "tags", "action_items", "key_details", "decisions", "open_questions")
    @classmethod
    def _normalize_string_lists(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def parse_llm_note_payload(
    raw: str | dict[str, Any],
    *,
    default_folder_choice: str | None = None,
    default_meeting_date: str | None = None,
) -> NotePayload:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise SchemaValidationError(f"LLM output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SchemaValidationError("LLM output must be a JSON object")
    payload = _normalize_llm_payload_shape(
        payload,
        default_folder_choice=default_folder_choice,
        default_meeting_date=default_meeting_date,
    )
    try:
        return NotePayload.model_validate(payload)
    except ValidationError as exc:
        raise SchemaValidationError(f"LLM output failed schema validation: {exc}") from exc


def ensure_folder_choice_candidate(note: NotePayload, candidate_folders: list[str]) -> None:
    if note.folder_choice not in candidate_folders:
        raise SchemaValidationError(
            f"folder_choice must be one of provided candidates: {candidate_folders}"
        )


def validate_note_length(note: NotePayload, *, max_total_chars: int = MAX_TOTAL_NOTE_CHARS) -> None:
    total_chars = len(note.summary)
    total_chars += sum(len(item) for item in note.action_items)
    total_chars += sum(len(item) for item in note.key_details)
    total_chars += sum(len(item) for item in (note.decisions or []))
    total_chars += sum(len(item) for item in (note.open_questions or []))
    if total_chars > max_total_chars:
        raise SchemaValidationError(
            f"Note payload too long ({total_chars} chars > {max_total_chars} chars)"
        )


_ALLOWED_FIELDS = {
    "title",
    "meeting_date",
    "attendees",
    "client",
    "project",
    "tags",
    "folder_choice",
    "summary",
    "action_items",
    "key_details",
    "decisions",
    "open_questions",
    "sensitive",
}


def _normalize_llm_payload_shape(
    payload: dict[str, Any],
    *,
    default_folder_choice: str | None,
    default_meeting_date: str | None,
) -> dict[str, Any]:
    merged = dict(payload)
    meeting_note = merged.get("meeting_note")
    if isinstance(meeting_note, dict):
        unwrapped = dict(meeting_note)
        # Top-level recognized keys override wrapper keys if present.
        for key, value in merged.items():
            if key != "meeting_note" and key in _ALLOWED_FIELDS:
                unwrapped[key] = value
        merged = unwrapped

    # Drop unknown keys to tolerate model shape drift (for example "attachments").
    normalized = {key: value for key, value in merged.items() if key in _ALLOWED_FIELDS}

    list_fields = ["attendees", "tags", "action_items", "key_details", "decisions", "open_questions"]
    for field in list_fields:
        normalized[field] = _coerce_to_string_list(normalized.get(field))

    if not isinstance(normalized.get("title"), str) or not str(normalized.get("title", "")).strip():
        normalized["title"] = "Meeting Notes"
    if not isinstance(normalized.get("summary"), str) or not str(normalized.get("summary", "")).strip():
        normalized["summary"] = "Summary unavailable from model output."
    normalized["meeting_date"] = _normalize_meeting_date_value(
        normalized.get("meeting_date"),
        default_meeting_date=default_meeting_date,
    )
    if default_folder_choice and (
        not isinstance(normalized.get("folder_choice"), str)
        or not str(normalized.get("folder_choice", "")).strip()
    ):
        normalized["folder_choice"] = default_folder_choice

    normalized["sensitive"] = _coerce_to_bool(normalized.get("sensitive"))
    return normalized


def _coerce_to_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else []
    if isinstance(value, dict):
        items: list[str] = []
        for key, item in value.items():
            key_s = str(key).strip()
            item_s = str(item).strip()
            if key_s and item_s:
                items.append(f"{key_s}: {item_s}")
            elif item_s:
                items.append(item_s)
            elif key_s:
                items.append(key_s)
        return [item for item in items if item]
    return [str(value).strip()] if str(value).strip() else []


def _coerce_to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "1"}:
            return True
        if lowered in {"false", "no", "n", "0", ""}:
            return False
    if isinstance(value, list):
        if not value:
            return False
        first = value[0]
        if isinstance(first, str):
            text = first.strip().lower()
            if any(token in text for token in ("sensitive", "pii", "ssn", "account number")):
                return True
        return False
    return False


def _normalize_meeting_date_value(value: Any, *, default_meeting_date: str | None) -> str:
    fallback = default_meeting_date or date.today().isoformat()
    if not isinstance(value, str):
        return fallback
    candidate = value.strip()
    if not candidate:
        return fallback
    try:
        parsed = date.fromisoformat(candidate)
    except ValueError:
        return fallback
    return parsed.isoformat()
