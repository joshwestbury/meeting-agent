from datetime import datetime
import re
from typing import Any, Callable

from meeting_agent.errors import SchemaValidationError
from meeting_agent.note_schema import (
    NotePayload,
    ensure_folder_choice_candidate,
    parse_llm_note_payload,
    validate_note_length,
)


_DEFAULT_SENSITIVE_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN-like
    re.compile(r"\b(account|routing)\b", re.IGNORECASE),
    re.compile(r"\b(legal|medical|diagnosis|patient|hipaa)\b", re.IGNORECASE),
]


def detect_sensitive(
    transcript_text: str,
    *,
    extra_patterns: list[str] | None = None,
    force_sensitive: bool = False,
) -> bool:
    if force_sensitive:
        return True

    patterns = list(_DEFAULT_SENSITIVE_PATTERNS)
    for pattern in extra_patterns or []:
        try:
            patterns.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            continue

    return any(pattern.search(transcript_text) for pattern in patterns)


def build_no_llm_payload(
    *,
    meeting_date: str | None = None,
    title: str = "Meeting Notes",
    folder_choice: str,
    tags: list[str] | None = None,
    sensitive: bool = False,
) -> NotePayload:
    resolved_date = meeting_date or datetime.now().date().isoformat()
    return NotePayload(
        title=title,
        meeting_date=resolved_date,
        attendees=[],
        client="",
        project="",
        tags=tags or ["meeting"],
        folder_choice=folder_choice,
        summary="LLM disabled; generated deterministic template.",
        action_items=[],
        key_details=["Transcript available in staging."],
        decisions=[],
        open_questions=[],
        sensitive=sensitive,
    )


def generate_note_payload_with_llm(
    transcript_text: str,
    candidate_folders: list[str],
    llm_callable: Callable[[str, list[str]], str | dict[str, Any]],
    *,
    max_total_chars: int = 60_000,
) -> NotePayload:
    if not candidate_folders:
        raise SchemaValidationError("candidate_folders must not be empty")

    llm_output = llm_callable(transcript_text, candidate_folders)
    note = parse_llm_note_payload(llm_output)
    ensure_folder_choice_candidate(note, candidate_folders)
    validate_note_length(note, max_total_chars=max_total_chars)
    return note
