import json
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


def parse_llm_note_payload(raw: str | dict[str, Any]) -> NotePayload:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise SchemaValidationError(f"LLM output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SchemaValidationError("LLM output must be a JSON object")
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
