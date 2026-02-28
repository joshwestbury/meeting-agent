from dataclasses import dataclass
import os
import time
from typing import Any

import httpx

from meeting_agent.config import AppConfig
from meeting_agent.errors import LinkValidationError, RetrievalError
from meeting_agent.links import parse_granola_link


AUTH_REQUIRED = "AUTH_REQUIRED"
NOT_FOUND = "NOT_FOUND"
RATE_LIMITED = "RATE_LIMITED"
NETWORK_ERROR = "NETWORK_ERROR"
PARSE_ERROR = "PARSE_ERROR"


@dataclass(frozen=True)
class RetrievalResult:
    granola_id: str
    meeting_id: str
    title: str | None
    started_at: str | None
    attendees: list[str]
    transcript_text: str
    raw_payload: dict[str, Any]


def retrieve_transcript(
    source_url: str,
    config: AppConfig,
    *,
    client: httpx.Client | None = None,
    max_retries: int = 2,
) -> RetrievalResult:
    parsed = _parse_link(source_url)
    if config.auth_mode == "manual_export":
        return _retrieve_from_manual_export(config, parsed.meeting_id)

    created_client = client is None
    http_client = client or httpx.Client()
    try:
        return _retrieve_remote(parsed.meeting_id, parsed.source_url, config, http_client, max_retries)
    finally:
        if created_client:
            http_client.close()


def _parse_link(source_url: str):
    try:
        return parse_granola_link(source_url)
    except LinkValidationError as exc:
        raise RetrievalError(PARSE_ERROR, str(exc)) from exc


def _retrieve_from_manual_export(config: AppConfig, meeting_id: str) -> RetrievalResult:
    transcript_path = config.staging_root / "transcripts" / f"{meeting_id}.txt"
    if not transcript_path.exists():
        raise RetrievalError(
            NOT_FOUND,
            f"manual_export mode expected transcript at {transcript_path}. Export the meeting first.",
        )
    try:
        transcript_text = transcript_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RetrievalError(PARSE_ERROR, f"Could not read transcript file: {transcript_path}") from exc

    return RetrievalResult(
        granola_id="",
        meeting_id=meeting_id,
        title=None,
        started_at=None,
        attendees=[],
        transcript_text=transcript_text,
        raw_payload={"source": "manual_export", "transcript_path": str(transcript_path)},
    )


def _retrieve_remote(
    meeting_id: str,
    source_url: str,
    config: AppConfig,
    client: httpx.Client,
    max_retries: int,
) -> RetrievalResult:
    headers = _build_auth_headers(config)
    endpoint = f"https://notes.granola.ai/api/v1/transcripts/{meeting_id}"

    attempts = max_retries + 1
    last_error: RetrievalError | None = None
    for attempt in range(attempts):
        try:
            response = client.get(endpoint, headers=headers, timeout=20.0)
        except httpx.TransportError as exc:
            last_error = RetrievalError(NETWORK_ERROR, f"Network error while retrieving transcript: {exc}")
            if attempt < attempts - 1:
                _retry_pause(attempt)
                continue
            raise last_error from exc

        if response.status_code in (429, 502, 503, 504):
            code = RATE_LIMITED if response.status_code == 429 else NETWORK_ERROR
            message = (
                "Granola rate limited this request"
                if code == RATE_LIMITED
                else f"Granola temporary server error: HTTP {response.status_code}"
            )
            last_error = RetrievalError(code, message)
            if attempt < attempts - 1:
                _retry_pause(attempt)
                continue
            raise last_error

        if response.status_code in (401, 403):
            raise RetrievalError(AUTH_REQUIRED, "Granola authentication failed or expired.")
        if response.status_code == 404:
            raise RetrievalError(NOT_FOUND, f"Meeting not found or inaccessible: {source_url}")
        if response.status_code >= 400:
            raise RetrievalError(NETWORK_ERROR, f"Unexpected HTTP error from Granola: {response.status_code}")

        payload = _parse_json_payload(response)
        return _payload_to_result(payload, meeting_id)

    if last_error is not None:
        raise last_error
    raise RetrievalError(NETWORK_ERROR, "Unknown retrieval failure")


def _retry_pause(attempt: int) -> None:
    time.sleep(0.05 * (2**attempt))


def _build_auth_headers(config: AppConfig) -> dict[str, str]:
    if config.auth_mode == "token":
        token_env_name = (config.auth_token_env or "").strip()
        if not token_env_name:
            raise RetrievalError(AUTH_REQUIRED, "Token auth mode requires auth_token_env.")
        token = os.environ.get(token_env_name)
        if not token:
            raise RetrievalError(
                AUTH_REQUIRED,
                f"Environment variable {token_env_name} is not set for token auth mode.",
            )
        return {"Authorization": f"Bearer {token}"}

    if config.auth_mode == "cookie":
        if config.cookie_file is None:
            raise RetrievalError(AUTH_REQUIRED, "Cookie auth mode requires cookie_file.")
        if not config.cookie_file.exists():
            raise RetrievalError(AUTH_REQUIRED, f"Cookie file not found: {config.cookie_file}")
        try:
            cookie_raw = config.cookie_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RetrievalError(
                AUTH_REQUIRED,
                f"Could not read cookie file: {config.cookie_file}",
            ) from exc
        if not cookie_raw:
            raise RetrievalError(AUTH_REQUIRED, f"Cookie file is empty: {config.cookie_file}")
        return {"Cookie": cookie_raw}

    raise RetrievalError(PARSE_ERROR, f"Unsupported auth mode for remote retrieval: {config.auth_mode}")


def _parse_json_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RetrievalError(PARSE_ERROR, "Granola response was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise RetrievalError(PARSE_ERROR, "Granola response payload must be an object.")
    return payload


def _payload_to_result(payload: dict[str, Any], fallback_meeting_id: str) -> RetrievalResult:
    transcript_text = (
        payload.get("transcript_text")
        or payload.get("transcript")
        or payload.get("text")
    )
    if not isinstance(transcript_text, str):
        raise RetrievalError(PARSE_ERROR, "Transcript text missing or not a string.")

    attendees = _normalize_attendees(payload.get("attendees"))
    granola_id_raw = payload.get("granola_id")
    if granola_id_raw is None:
        granola_id_raw = payload.get("id")
    granola_id = str(granola_id_raw) if granola_id_raw is not None else ""
    meeting_id_raw = payload.get("meeting_id")
    meeting_id = str(meeting_id_raw) if meeting_id_raw is not None else fallback_meeting_id

    title = payload.get("title")
    started_at = payload.get("started_at") or payload.get("start_time")
    return RetrievalResult(
        granola_id=granola_id,
        meeting_id=meeting_id,
        title=str(title) if isinstance(title, str) else None,
        started_at=str(started_at) if isinstance(started_at, str) else None,
        attendees=attendees,
        transcript_text=transcript_text,
        raw_payload=payload,
    )


def _normalize_attendees(attendees_raw: Any) -> list[str]:
    if attendees_raw is None:
        return []
    if not isinstance(attendees_raw, list):
        return []

    attendees: list[str] = []
    for item in attendees_raw:
        if isinstance(item, str) and item.strip():
            attendees.append(item.strip())
            continue
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                attendees.append(name.strip())
    return attendees
