from dataclasses import dataclass
import os
import time
from typing import Any

import httpx

from meeting_agent.auth import (
    get_desktop_session_access_token,
    refresh_desktop_session_credentials,
)
from meeting_agent.config import AppConfig
from meeting_agent.errors import LinkValidationError, RetrievalError
from meeting_agent.links import parse_granola_link


AUTH_REQUIRED = "AUTH_REQUIRED"
NOT_FOUND = "NOT_FOUND"
RATE_LIMITED = "RATE_LIMITED"
NETWORK_ERROR = "NETWORK_ERROR"
PARSE_ERROR = "PARSE_ERROR"

GRANOLA_API_BASE_URL = "https://api.granola.ai"
GRANOLA_APP_VERSION = "7.0.0"


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
        return _retrieve_remote(
            parsed.raw_token,
            parsed.meeting_id,
            parsed.source_url,
            config,
            http_client,
            max_retries,
        )
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
    resource_id: str,
    fallback_meeting_id: str,
    source_url: str,
    config: AppConfig,
    client: httpx.Client,
    max_retries: int,
) -> RetrievalResult:
    headers = _build_auth_headers(config)
    primary_document_id = fallback_meeting_id
    fallback_document_id = resource_id if resource_id != fallback_meeting_id else None
    document_id = primary_document_id
    refreshed_after_unauthorized = False
    tried_fallback_document_id = False

    attempts = max_retries + 1
    attempt = 0
    last_error: RetrievalError | None = None
    while attempt < attempts:
        try:
            response = client.post(
                f"{GRANOLA_API_BASE_URL}/v1/get-document-transcript",
                headers=_granola_client_headers(headers),
                json={"document_id": document_id},
                timeout=20.0,
            )
        except httpx.TransportError as exc:
            last_error = RetrievalError(NETWORK_ERROR, f"Network error while retrieving transcript: {exc}")
            if attempt < attempts - 1:
                _retry_pause(attempt)
                attempt += 1
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
                attempt += 1
                continue
            raise last_error

        if response.status_code in (401, 403):
            if config.auth_mode == "desktop_session" and not refreshed_after_unauthorized:
                new_creds = refresh_desktop_session_credentials(client=client)
                headers = {"Authorization": f"Bearer {new_creds.access_token}"}
                refreshed_after_unauthorized = True
                # Immediate retry after credential refresh; do not consume retry budget.
                continue
            raise RetrievalError(AUTH_REQUIRED, "Granola authentication failed or expired.")
        if response.status_code == 404:
            if fallback_document_id and not tried_fallback_document_id:
                document_id = fallback_document_id
                tried_fallback_document_id = True
                # Immediate retry on fallback endpoint; do not consume retry budget.
                continue
            raise RetrievalError(NOT_FOUND, f"Meeting not found or inaccessible: {source_url}")
        if response.status_code >= 400:
            raise RetrievalError(NETWORK_ERROR, f"Unexpected HTTP error from Granola: {response.status_code}")

        payload = _parse_json_payload(response)
        return _payload_to_result(payload, fallback_meeting_id)
        # no loop increment needed on return

    # loop exhausted

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

    if config.auth_mode == "desktop_session":
        token = get_desktop_session_access_token()
        return {"Authorization": f"Bearer {token}"}

    raise RetrievalError(PARSE_ERROR, f"Unsupported auth mode for remote retrieval: {config.auth_mode}")


def _parse_json_payload(response: httpx.Response) -> dict[str, Any] | list[Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RetrievalError(PARSE_ERROR, "Granola response was not valid JSON.") from exc
    if not isinstance(payload, (dict, list)):
        raise RetrievalError(PARSE_ERROR, "Granola response payload must be an object or array.")
    return payload


def _payload_to_result(payload: dict[str, Any] | list[Any], fallback_meeting_id: str) -> RetrievalResult:
    transcript_text, attendees, granola_id, meeting_id, title, started_at, raw_payload = _extract_payload_fields(
        payload,
        fallback_meeting_id,
    )

    return RetrievalResult(
        granola_id=granola_id,
        meeting_id=meeting_id,
        title=title,
        started_at=started_at,
        attendees=attendees,
        transcript_text=transcript_text,
        raw_payload=raw_payload,
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


def _granola_client_headers(auth_headers: dict[str, str]) -> dict[str, str]:
    return {
        **auth_headers,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "User-Agent": f"Granola/{GRANOLA_APP_VERSION}",
        "X-Client-Version": GRANOLA_APP_VERSION,
        "X-App-Version": GRANOLA_APP_VERSION,
        "X-Client-Type": "cli",
    }


def _extract_payload_fields(
    payload: dict[str, Any] | list[Any],
    fallback_meeting_id: str,
) -> tuple[str, list[str], str, str, str | None, str | None, dict[str, Any]]:
    if isinstance(payload, list):
        transcript_text = _segments_to_text(payload)
        return (
            transcript_text,
            [],
            "",
            fallback_meeting_id,
            None,
            None,
            {"transcript_segments": payload},
        )

    transcript_text = payload.get("transcript_text") or payload.get("transcript") or payload.get("text")
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
    return (
        transcript_text,
        attendees,
        granola_id,
        meeting_id,
        str(title) if isinstance(title, str) else None,
        str(started_at) if isinstance(started_at, str) else None,
        payload,
    )


def _segments_to_text(segments: list[Any]) -> str:
    lines: list[str] = []
    for segment in segments:
        if isinstance(segment, dict):
            text = segment.get("text")
            if isinstance(text, str) and text.strip():
                lines.append(text.strip())
    if lines:
        return "\n".join(lines)
    return ""
