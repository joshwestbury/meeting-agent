from datetime import datetime
import json
import re
from typing import Any, Callable

import httpx

from meeting_agent.errors import SchemaValidationError
from meeting_agent.note_schema import (
    NotePayload,
    ensure_folder_choice_candidate,
    parse_llm_note_payload,
    validate_note_length,
)


def build_no_llm_payload(
    *,
    meeting_date: str | None = None,
    title: str = "Meeting Notes",
    folder_choice: str,
    tags: list[str] | None = None,
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
        sensitive=False,
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
    note = parse_llm_note_payload(
        llm_output,
        default_folder_choice=candidate_folders[0],
    )
    ensure_folder_choice_candidate(note, candidate_folders)
    validate_note_length(note, max_total_chars=max_total_chars)
    return note


def generate_note_payload_with_local_runtime(
    transcript_text: str,
    candidate_folders: list[str],
    *,
    model: str,
    server_url: str,
    client: httpx.Client | None = None,
    max_total_chars: int = 60_000,
) -> NotePayload:
    if not candidate_folders:
        raise SchemaValidationError("candidate_folders must not be empty")

    llm_output = call_local_llama_server(
        transcript_text,
        candidate_folders,
        model=model,
        server_url=server_url,
        client=client,
    )
    note = parse_llm_note_payload(
        llm_output,
        default_folder_choice=candidate_folders[0],
    )
    ensure_folder_choice_candidate(note, candidate_folders)
    validate_note_length(note, max_total_chars=max_total_chars)
    return note


def choose_candidate_folder_with_local_runtime(
    folder_hint: str,
    candidate_folders: list[str],
    *,
    model: str,
    server_url: str,
    client: httpx.Client | None = None,
) -> str:
    if not candidate_folders:
        raise SchemaValidationError("candidate_folders must not be empty")

    prompt = _build_folder_choice_prompt(folder_hint, candidate_folders)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Select exactly one folder from the numbered list. "
                    "Reply with only the numeric index."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
    }

    endpoint = f"{server_url.rstrip('/')}/v1/chat/completions"
    created_client = client is None
    http_client = client or httpx.Client()
    try:
        try:
            response = http_client.post(endpoint, json=payload, timeout=20.0)
        except httpx.TransportError as exc:
            raise SchemaValidationError(f"Local LLM server request failed: {exc}") from exc

        if response.status_code >= 400:
            raise SchemaValidationError(
                f"Local LLM server returned HTTP {response.status_code}"
            )

        data = _parse_runtime_json(response)
        selection_raw = _extract_message_content(data)
        index = _extract_folder_index(selection_raw, max_index=len(candidate_folders))
        return candidate_folders[index - 1]
    finally:
        if created_client:
            http_client.close()


def call_local_llama_server(
    transcript_text: str,
    candidate_folders: list[str],
    *,
    model: str,
    server_url: str,
    client: httpx.Client | None = None,
) -> str:
    prompt = _build_prompt(transcript_text, candidate_folders)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a meeting-note formatter. Return JSON only with keys: "
                    "title, meeting_date, attendees, client, project, tags, folder_choice, "
                    "summary, action_items, key_details, decisions, open_questions, sensitive."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }

    endpoint = f"{server_url.rstrip('/')}/v1/chat/completions"
    created_client = client is None
    http_client = client or httpx.Client()
    try:
        try:
            response = http_client.post(endpoint, json=payload, timeout=30.0)
        except httpx.TransportError as exc:
            raise SchemaValidationError(f"Local LLM server request failed: {exc}") from exc

        if response.status_code >= 400:
            raise SchemaValidationError(
                f"Local LLM server returned HTTP {response.status_code}"
            )

        data = _parse_runtime_json(response)
        return _extract_message_content(data)
    finally:
        if created_client:
            http_client.close()


def _build_prompt(transcript_text: str, candidate_folders: list[str]) -> str:
    folders = "\n".join(f"- {folder}" for folder in candidate_folders)
    return (
        f"Candidate folders:\n{folders}\n\n"
        "Return exactly one valid JSON object. Use folder_choice from candidate folders only.\n\n"
        f"Transcript:\n{transcript_text}"
    )


def _build_folder_choice_prompt(folder_hint: str, candidate_folders: list[str]) -> str:
    choices = "\n".join(f"{idx}. {folder}" for idx, folder in enumerate(candidate_folders, start=1))
    return (
        f"User folder hint: {folder_hint}\n\n"
        "Candidate folders:\n"
        f"{choices}\n\n"
        "Return only one number for the best folder."
    )


def _parse_runtime_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise SchemaValidationError("Local LLM server returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise SchemaValidationError("Local LLM server response must be a JSON object")
    return data


def _extract_message_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SchemaValidationError("Local LLM response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise SchemaValidationError("Local LLM response choice is invalid")

    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return _coerce_json_string(content)

    text = first.get("text")
    if isinstance(text, str) and text.strip():
        return _coerce_json_string(text)

    raise SchemaValidationError("Local LLM response missing message content")


def _coerce_json_string(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()
    try:
        json.loads(cleaned)
    except json.JSONDecodeError:
        return cleaned
    return cleaned


def _extract_folder_index(content: str, *, max_index: int) -> int:
    cleaned = content.strip()
    match = re.search(r"\b(\d+)\b", cleaned)
    if not match:
        raise SchemaValidationError("Local LLM folder-selection response missing numeric index")
    index = int(match.group(1))
    if index < 1 or index > max_index:
        raise SchemaValidationError(
            f"Local LLM folder-selection index out of range: {index} (1-{max_index})"
        )
    return index
