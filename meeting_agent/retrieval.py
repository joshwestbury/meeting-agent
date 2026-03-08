from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, tzinfo
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


@dataclass(frozen=True)
class MeetingCandidate:
    document_id: str
    meeting_id: str
    title: str | None
    started_at: str | None
    has_transcript: bool
    source_url: str


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


def list_meetings_for_day(
    config: AppConfig,
    target_date: date,
    *,
    timezone_name: str = "local",
    client: httpx.Client | None = None,
    max_retries: int = 1,
) -> list[MeetingCandidate]:
    if config.auth_mode == "manual_export":
        raise RetrievalError(
            PARSE_ERROR,
            "Meeting discovery requires remote auth mode (`token`, `cookie`, or `desktop_session`).",
        )

    created_client = client is None
    http_client = client or httpx.Client()
    try:
        headers = _build_auth_headers(config)
        timezone_value = _resolve_timezone_name(timezone_name)
        start_at = datetime.combine(target_date, dt_time.min, tzinfo=timezone_value)
        end_at = start_at + timedelta(days=1)
        discovery_payload = _request_discovery_payload(
            client=http_client,
            headers=headers,
            config=config,
            window_start=start_at,
            window_end=end_at,
            max_retries=max_retries,
        )
        candidates = _extract_meeting_candidates(
            payload=discovery_payload,
            target_date=target_date,
            timezone_name=timezone_name,
        )
        candidates = _filter_candidates_with_available_transcripts(
            candidates=candidates,
            headers=headers,
            config=config,
            client=http_client,
            max_retries=max_retries,
        )
        candidates.sort(key=lambda item: (item.started_at or "", item.title or "", item.meeting_id))
        return candidates
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
        result = _payload_to_result(payload, fallback_meeting_id)
        if _needs_document_metadata_fallback(result, payload):
            metadata = _fetch_document_metadata(
                document_id=document_id,
                headers=headers,
                client=client,
            )
            result = _merge_result_with_document_metadata(result, metadata)
        return result
        # no loop increment needed on return

    # loop exhausted

    if last_error is not None:
        raise last_error
    raise RetrievalError(NETWORK_ERROR, "Unknown retrieval failure")


def _request_discovery_payload(
    *,
    client: httpx.Client,
    headers: dict[str, str],
    config: AppConfig,
    window_start: datetime,
    window_end: datetime,
    max_retries: int,
) -> dict[str, Any] | list[Any]:
    attempts = max_retries + 1
    refreshed_after_unauthorized = False
    auth_headers = headers
    last_error: RetrievalError | None = None
    endpoints = (
        "/v1/get-documents",
        "/v1/list-documents",
    )
    payloads = _build_discovery_payload_candidates(window_start, window_end)
    last_non_404_error: RetrievalError | None = None

    for path in endpoints:
        for payload in payloads:
            attempt = 0
            while attempt < attempts:
                try:
                    response = client.post(
                        f"{GRANOLA_API_BASE_URL}{path}",
                        headers=_granola_client_headers(auth_headers),
                        json=payload,
                        timeout=20.0,
                    )
                except httpx.TransportError as exc:
                    last_error = RetrievalError(NETWORK_ERROR, f"Network error while listing meetings: {exc}")
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
                        auth_headers = {"Authorization": f"Bearer {new_creds.access_token}"}
                        refreshed_after_unauthorized = True
                        continue
                    raise RetrievalError(AUTH_REQUIRED, "Granola authentication failed or expired.")

                if response.status_code == 404:
                    break
                if response.status_code >= 400:
                    last_non_404_error = RetrievalError(
                        NETWORK_ERROR,
                        f"Unexpected discovery HTTP error from Granola: {response.status_code}",
                    )
                    break

                payload_value = _parse_json_payload(response)
                if _extract_discovery_docs(payload_value):
                    return payload_value
                # Endpoint accepted but this query shape returned no docs; try next shape.
                break

    if last_error is not None:
        raise last_error
    if last_non_404_error is not None:
        raise last_non_404_error
    raise RetrievalError(
        PARSE_ERROR,
        "Could not discover meetings from Granola API. Run `meeting-agent auth-check <granola_link>` to verify access.",
    )


def _build_discovery_payload_candidates(window_start: datetime, window_end: datetime) -> list[dict[str, Any]]:
    return [
        {
            "started_after": window_start.isoformat(),
            "started_before": window_end.isoformat(),
            "include_archived": False,
        },
        {
            "start_time": window_start.isoformat(),
            "end_time": window_end.isoformat(),
            "include_archived": False,
        },
        {
            "from": window_start.isoformat(),
            "to": window_end.isoformat(),
            "include_archived": False,
        },
        {"include_archived": False, "limit": 200},
        {},
    ]


def _extract_meeting_candidates(
    *,
    payload: dict[str, Any] | list[Any],
    target_date: date,
    timezone_name: str,
) -> list[MeetingCandidate]:
    docs = _extract_discovery_docs(payload)
    timezone_value = _resolve_timezone_name(timezone_name)
    candidates: list[MeetingCandidate] = []
    for doc in docs:
        candidate = _doc_to_meeting_candidate(doc, timezone_value)
        if candidate is None:
            continue
        if candidate.started_at is None:
            continue
        started_at = _parse_datetime(candidate.started_at)
        if started_at is None:
            continue
        if started_at.astimezone(timezone_value).date() != target_date:
            continue
        candidates.append(candidate)
    return candidates


def _extract_discovery_docs(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("docs", "documents", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _doc_to_meeting_candidate(doc: dict[str, Any], timezone_value: tzinfo) -> MeetingCandidate | None:
    meeting_id = _first_nonempty_str(doc.get("meeting_id"), doc.get("id"), doc.get("document_id"))
    if not meeting_id:
        return None
    source_url = f"https://notes.granola.ai/d/{meeting_id}"
    try:
        parse_granola_link(source_url)
    except LinkValidationError:
        return None

    started_at = _first_nonempty_str(doc.get("started_at"), doc.get("start_time"), doc.get("created_at"))
    if started_at:
        parsed = _parse_datetime(started_at)
        if parsed is not None:
            started_at = parsed.astimezone(timezone_value).isoformat()

    return MeetingCandidate(
        document_id=_first_nonempty_str(doc.get("id"), doc.get("document_id"), meeting_id) or meeting_id,
        meeting_id=meeting_id,
        title=_first_nonempty_str(doc.get("title"), doc.get("name")),
        started_at=started_at,
        has_transcript=_doc_has_transcript(doc),
        source_url=source_url,
    )


def _filter_candidates_with_available_transcripts(
    *,
    candidates: list[MeetingCandidate],
    headers: dict[str, str],
    config: AppConfig,
    client: httpx.Client,
    max_retries: int,
) -> list[MeetingCandidate]:
    filtered: list[MeetingCandidate] = []
    for candidate in candidates:
        if candidate.has_transcript:
            filtered.append(candidate)
            continue
        if _candidate_has_retrievable_transcript(
            candidate=candidate,
            headers=headers,
            config=config,
            client=client,
            max_retries=max_retries,
        ):
            filtered.append(
                MeetingCandidate(
                    document_id=candidate.document_id,
                    meeting_id=candidate.meeting_id,
                    title=candidate.title,
                    started_at=candidate.started_at,
                    has_transcript=True,
                    source_url=candidate.source_url,
                )
            )
    return filtered


def _candidate_has_retrievable_transcript(
    *,
    candidate: MeetingCandidate,
    headers: dict[str, str],
    config: AppConfig,
    client: httpx.Client,
    max_retries: int,
) -> bool:
    attempts = max_retries + 1
    refreshed_after_unauthorized = False
    auth_headers = headers
    candidate_ids = [candidate.document_id]
    if candidate.meeting_id != candidate.document_id:
        candidate_ids.append(candidate.meeting_id)

    for document_id in candidate_ids:
        attempt = 0
        while attempt < attempts:
            try:
                response = client.post(
                    f"{GRANOLA_API_BASE_URL}/v1/get-document-transcript",
                    headers=_granola_client_headers(auth_headers),
                    json={"document_id": document_id},
                    timeout=20.0,
                )
            except httpx.TransportError:
                return False

            if response.status_code in (401, 403):
                if config.auth_mode == "desktop_session" and not refreshed_after_unauthorized:
                    new_creds = refresh_desktop_session_credentials(client=client)
                    auth_headers = {"Authorization": f"Bearer {new_creds.access_token}"}
                    refreshed_after_unauthorized = True
                    continue
                raise RetrievalError(AUTH_REQUIRED, "Granola authentication failed or expired.")
            if response.status_code in (429, 502, 503, 504):
                if attempt < attempts - 1:
                    _retry_pause(attempt)
                    attempt += 1
                    continue
                return False
            if response.status_code == 404:
                break
            if response.status_code >= 400:
                return False

            payload = _parse_json_payload(response)
            try:
                result = _payload_to_result(payload, candidate.meeting_id)
            except RetrievalError:
                return False
            return bool(result.transcript_text.strip())
    return False


def _doc_has_transcript(doc: dict[str, Any]) -> bool:
    for key in ("has_transcript", "transcript_available", "hasTranscript", "is_transcribed"):
        value = doc.get(key)
        if isinstance(value, bool):
            return value
    text = doc.get("transcript_text") or doc.get("transcript")
    if isinstance(text, str) and text.strip():
        return True
    segments = doc.get("transcript_segments")
    if isinstance(segments, list) and bool(segments):
        return True
    status = doc.get("transcript_status")
    if isinstance(status, str) and status.strip().casefold() in {"ready", "completed", "available"}:
        return True
    return False


def _first_nonempty_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_datetime(value: str) -> datetime | None:
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def _resolve_timezone_name(timezone_name: str) -> tzinfo:
    local_timezone = datetime.now().astimezone().tzinfo
    if local_timezone is None:  # pragma: no cover
        from datetime import timezone

        local_timezone = timezone.utc
    if timezone_name == "local":
        return local_timezone
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(timezone_name)
    except Exception:
        return local_timezone


def _retry_pause(attempt: int) -> None:
    time.sleep(0.05 * (2**attempt))


def _needs_document_metadata_fallback(result: RetrievalResult, payload: dict[str, Any] | list[Any]) -> bool:
    if result.title and result.started_at:
        return False
    if isinstance(payload, list):
        return True
    if not isinstance(payload, dict):
        return False
    # Granola sometimes returns transcript-only payloads under `transcript_segments`.
    return "transcript_segments" in payload


def _fetch_document_metadata(
    *,
    document_id: str,
    headers: dict[str, str],
    client: httpx.Client,
) -> dict[str, Any] | None:
    try:
        response = client.post(
            f"{GRANOLA_API_BASE_URL}/v1/get-documents-batch",
            headers=_granola_client_headers(headers),
            json={
                "document_ids": [document_id],
                "include_last_viewed_panel": True,
            },
            timeout=20.0,
        )
    except httpx.TransportError:
        return None
    if response.status_code >= 400:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    docs = payload.get("docs")
    if not isinstance(docs, list):
        return None
    for doc in docs:
        if isinstance(doc, dict) and str(doc.get("id", "")) == document_id:
            return doc
    return None


def _merge_result_with_document_metadata(
    result: RetrievalResult,
    metadata: dict[str, Any] | None,
) -> RetrievalResult:
    if not metadata:
        return result
    title = result.title
    if not title:
        raw_title = metadata.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            title = raw_title.strip()
    started_at = result.started_at
    if not started_at:
        raw_started_at = metadata.get("started_at")
        if not isinstance(raw_started_at, str) or not raw_started_at.strip():
            raw_started_at = metadata.get("created_at")
        if isinstance(raw_started_at, str) and raw_started_at.strip():
            started_at = raw_started_at.strip()
    if title == result.title and started_at == result.started_at:
        return result
    return RetrievalResult(
        granola_id=result.granola_id,
        meeting_id=result.meeting_id,
        title=title,
        started_at=started_at,
        attendees=result.attendees,
        transcript_text=result.transcript_text,
        raw_payload=result.raw_payload,
    )


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
        segments = payload.get("transcript_segments")
        if isinstance(segments, list):
            transcript_text = _segments_to_text(segments)
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
