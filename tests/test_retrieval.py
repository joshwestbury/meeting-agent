from datetime import date
from pathlib import Path
from typing import Literal

import httpx
import pytest

from meeting_agent.config import AppConfig
from meeting_agent.errors import RetrievalError
from meeting_agent.retrieval import (
    AUTH_REQUIRED,
    MeetingCandidate,
    NETWORK_ERROR,
    NOT_FOUND,
    PARSE_ERROR,
    RATE_LIMITED,
    list_meetings_for_day,
    retrieve_transcript,
)


def _base_config(
    tmp_path: Path, auth_mode: Literal["token", "cookie", "manual_export", "desktop_session"] = "token"
) -> AppConfig:
    vault_root = tmp_path / "vault"
    vault_root.mkdir(exist_ok=True)
    return AppConfig(
        vault_root=vault_root,
        staging_root=tmp_path / "staging",
        auth_mode=auth_mode,
        auth_token_env="MEETING_AGENT_TOKEN",
    )


def test_retrieve_transcript_success_token_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.method == "POST"
        assert request.url.host == "api.granola.ai"
        assert request.url.path == "/v1/get-document-transcript"
        assert request.read().decode("utf-8").find("29250e01-0751-4e02-9b24-f6d06f878b04") != -1
        return httpx.Response(
            200,
            json={
                "granola_id": "g-123",
                "meeting_id": "29250e01-0751-4e02-9b24-f6d06f878b04",
                "title": "Weekly Sync",
                "started_at": "2026-02-28T10:00:00-06:00",
                "attendees": [{"name": "Alex"}, "Jamie"],
                "transcript_text": "hello world",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = retrieve_transcript(
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        config,
        client=client,
    )

    assert result.granola_id == "g-123"
    assert result.meeting_id == "29250e01-0751-4e02-9b24-f6d06f878b04"
    assert result.title == "Weekly Sync"
    assert result.attendees == ["Alex", "Jamie"]
    assert result.transcript_text == "hello world"
    client.close()


def test_retrieve_transcript_uses_uuid_document_id_for_t_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")
    called_document_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        if "29250e01-0751-4e02-9b24-f6d06f878b04-00b881l8" in body:
            called_document_ids.append("raw_token")
            return httpx.Response(404, json={"error": "not found"})
        if "29250e01-0751-4e02-9b24-f6d06f878b04" in body:
            called_document_ids.append("uuid")
            return httpx.Response(200, json={"transcript_text": "ok"})
        return httpx.Response(500, json={"error": "unexpected"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = retrieve_transcript(
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04-00b881l8",
        config,
        client=client,
        max_retries=0,
    )

    assert result.transcript_text == "ok"
    assert called_document_ids == ["uuid"]
    client.close()


def test_retrieve_transcript_auth_required_missing_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEETING_AGENT_TOKEN", raising=False)
    config = _base_config(tmp_path, "token")

    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            config,
        )

    assert exc.value.code == AUTH_REQUIRED


def test_retrieve_transcript_malformed_link_maps_parse_error(tmp_path: Path) -> None:
    config = _base_config(tmp_path, "manual_export")

    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript("https://notes.granola.ai/x/not-a-token", config)

    assert exc.value.code == PARSE_ERROR


def test_retrieve_transcript_not_found_maps_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            config,
            client=client,
        )
    assert exc.value.code == NOT_FOUND
    client.close()


@pytest.mark.parametrize("status_code", [401, 403])
def test_retrieve_transcript_auth_required_from_http_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "auth"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            config,
            client=client,
        )
    assert exc.value.code == AUTH_REQUIRED
    client.close()


def test_retrieve_transcript_rate_limited_maps_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limit"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            config,
            client=client,
            max_retries=1,
        )
    assert exc.value.code == RATE_LIMITED
    client.close()


def test_retrieve_transcript_rate_limited_retries_then_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")
    calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(429, json={"error": "rate limit"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            config,
            client=client,
            max_retries=2,
        )
    assert calls["count"] == 3
    assert exc.value.code == RATE_LIMITED
    client.close()


def test_retrieve_transcript_network_error_maps_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            config,
            client=client,
            max_retries=1,
        )
    assert exc.value.code == NETWORK_ERROR
    client.close()


def test_retrieve_transcript_parse_error_maps_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"title": "No transcript key"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            config,
            client=client,
        )
    assert exc.value.code == PARSE_ERROR
    client.close()


def test_retrieve_transcript_parse_error_on_invalid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="{not-valid-json")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            config,
            client=client,
        )
    assert exc.value.code == PARSE_ERROR
    client.close()


def test_retrieve_transcript_accepts_array_payload_as_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"text": "first line"},
                {"text": "second line"},
            ],
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = retrieve_transcript(
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        config,
        client=client,
    )
    assert result.transcript_text == "first line\nsecond line"
    client.close()


def test_retrieve_transcript_retries_transient_failure_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")
    calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json={"transcript_text": "ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = retrieve_transcript(
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        config,
        client=client,
        max_retries=2,
    )

    assert calls["count"] == 2
    assert result.transcript_text == "ok"
    client.close()


@pytest.mark.parametrize("key", ["transcript", "text"])
def test_retrieve_transcript_accepts_transcript_fallback_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={key: "alt transcript"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = retrieve_transcript(
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        config,
        client=client,
    )
    assert result.transcript_text == "alt transcript"
    client.close()


def test_retrieve_transcript_manual_export_reads_staged_file(tmp_path: Path) -> None:
    config = _base_config(tmp_path, "manual_export")
    transcript_dir = config.staging_root / "transcripts"
    transcript_dir.mkdir(parents=True)
    transcript_file = transcript_dir / "29250e01-0751-4e02-9b24-f6d06f878b04.txt"
    transcript_file.write_text("manual transcript", encoding="utf-8")

    result = retrieve_transcript(
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        config,
    )

    assert result.transcript_text == "manual transcript"
    assert result.raw_payload["source"] == "manual_export"


def test_retrieve_transcript_manual_export_missing_file_is_actionable(tmp_path: Path) -> None:
    config = _base_config(tmp_path, "manual_export")

    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            config,
        )

    assert exc.value.code == NOT_FOUND
    assert "manual_export mode expected transcript" in str(exc.value)


def test_retrieve_transcript_cookie_mode_reads_cookie_file(
    tmp_path: Path,
) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("session=abc123", encoding="utf-8")
    config = AppConfig(
        vault_root=(tmp_path / "vault"),
        staging_root=tmp_path / "staging",
        auth_mode="cookie",
        cookie_file=cookie_file,
    )
    config.vault_root.mkdir(exist_ok=True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Cookie"] == "session=abc123"
        return httpx.Response(200, json={"transcript_text": "cookie transcript"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = retrieve_transcript(
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        config,
        client=client,
    )
    assert result.transcript_text == "cookie transcript"
    client.close()


def test_retrieve_transcript_cookie_mode_missing_file_is_auth_required(tmp_path: Path) -> None:
    config = AppConfig(
        vault_root=(tmp_path / "vault"),
        staging_root=tmp_path / "staging",
        auth_mode="cookie",
        cookie_file=tmp_path / "missing-cookies.txt",
    )
    config.vault_root.mkdir(exist_ok=True)

    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            config,
        )
    assert exc.value.code == AUTH_REQUIRED


def test_retrieve_transcript_cookie_mode_empty_file_is_auth_required(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("   ", encoding="utf-8")
    config = AppConfig(
        vault_root=(tmp_path / "vault"),
        staging_root=tmp_path / "staging",
        auth_mode="cookie",
        cookie_file=cookie_file,
    )
    config.vault_root.mkdir(exist_ok=True)

    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            config,
        )
    assert exc.value.code == AUTH_REQUIRED


def test_retrieve_transcript_cookie_mode_unreadable_file_is_auth_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("session=abc123", encoding="utf-8")
    config = AppConfig(
        vault_root=(tmp_path / "vault"),
        staging_root=tmp_path / "staging",
        auth_mode="cookie",
        cookie_file=cookie_file,
    )
    config.vault_root.mkdir(exist_ok=True)

    original_read_text = Path.read_text

    def _raise_read_text(self: Path, encoding: str = "utf-8") -> str:
        if self == cookie_file:
            raise OSError("permission denied")
        return original_read_text(self, encoding=encoding)

    monkeypatch.setattr(Path, "read_text", _raise_read_text, raising=True)

    with pytest.raises(RetrievalError) as exc:
        retrieve_transcript(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            config,
        )
    assert exc.value.code == AUTH_REQUIRED
    assert "Could not read cookie file" in str(exc.value)


def test_retrieve_transcript_desktop_session_uses_bearer_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _base_config(tmp_path, "desktop_session")
    monkeypatch.setattr("meeting_agent.retrieval.get_desktop_session_access_token", lambda: "desktop-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer desktop-token"
        return httpx.Response(200, json={"transcript_text": "desktop transcript"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = retrieve_transcript(
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        config,
        client=client,
    )
    assert result.transcript_text == "desktop transcript"
    client.close()


def test_retrieve_transcript_desktop_session_refreshes_once_on_401(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _base_config(tmp_path, "desktop_session")
    monkeypatch.setattr("meeting_agent.retrieval.get_desktop_session_access_token", lambda: "stale-token")

    class _Creds:
        access_token = "fresh-token"

    monkeypatch.setattr(
        "meeting_agent.retrieval.refresh_desktop_session_credentials",
        lambda client=None: _Creds(),
    )

    seen_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("Authorization", ""))
        if len(seen_headers) == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"transcript_text": "ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = retrieve_transcript(
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        config,
        client=client,
        max_retries=0,
    )
    assert result.transcript_text == "ok"
    assert seen_headers == ["Bearer stale-token", "Bearer fresh-token"]
    client.close()


def test_retrieve_transcript_desktop_session_reimports_after_rejected_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _base_config(tmp_path, "desktop_session")
    monkeypatch.setattr("meeting_agent.retrieval.get_desktop_session_access_token", lambda: "stale-token")

    class _Creds:
        def __init__(self, access_token: str) -> None:
            self.access_token = access_token

    monkeypatch.setattr(
        "meeting_agent.retrieval.refresh_desktop_session_credentials",
        lambda client=None: _Creds("refreshed-token"),
    )
    monkeypatch.setattr(
        "meeting_agent.retrieval.import_desktop_session_credentials",
        lambda: _Creds("imported-token"),
    )

    seen_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("Authorization", ""))
        if request.headers.get("Authorization") != "Bearer imported-token":
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"transcript_text": "ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = retrieve_transcript(
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        config,
        client=client,
        max_retries=0,
    )

    assert result.transcript_text == "ok"
    assert seen_headers == [
        "Bearer stale-token",
        "Bearer refreshed-token",
        "Bearer imported-token",
    ]
    client.close()


def test_retrieve_transcript_enriches_title_from_documents_batch_when_segments_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/get-document-transcript":
            return httpx.Response(
                200,
                json=[
                    {"text": "first line"},
                    {"text": "second line"},
                ],
            )
        if request.url.path == "/v1/get-documents-batch":
            return httpx.Response(
                200,
                json={
                    "docs": [
                        {
                            "id": "29250e01-0751-4e02-9b24-f6d06f878b04",
                            "title": "[Internal] Dialpad CPQ / Integration Sync",
                            "created_at": "2026-03-06T18:30:57.148Z",
                        }
                    ]
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = retrieve_transcript(
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        config,
        client=client,
        max_retries=0,
    )
    assert result.transcript_text == "first line\nsecond line"
    assert result.title == "[Internal] Dialpad CPQ / Integration Sync"
    assert result.started_at == "2026-03-06T18:30:57.148Z"
    client.close()


def test_list_meetings_for_day_discovers_and_filters_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/get-documents":
            return httpx.Response(
                200,
                json={
                    "docs": [
                        {
                            "id": "29250e01-0751-4e02-9b24-f6d06f878b04",
                            "meeting_id": "29250e01-0751-4e02-9b24-f6d06f878b04",
                            "title": "Included",
                            "started_at": "2026-03-07T09:00:00-06:00",
                            "has_transcript": True,
                        },
                        {
                            "id": "29250e01-0751-4e02-9b24-f6d06f878b05",
                            "meeting_id": "29250e01-0751-4e02-9b24-f6d06f878b05",
                            "title": "Wrong day",
                            "started_at": "2026-03-06T09:00:00-06:00",
                            "has_transcript": True,
                        },
                        {
                            "id": "29250e01-0751-4e02-9b24-f6d06f878b06",
                            "meeting_id": "29250e01-0751-4e02-9b24-f6d06f878b06",
                            "title": "No transcript",
                            "started_at": "2026-03-07T11:00:00-06:00",
                            "has_transcript": False,
                        },
                    ]
                },
            )
        if request.url.path == "/v1/get-document-transcript":
            if "29250e01-0751-4e02-9b24-f6d06f878b06" in request.content.decode("utf-8"):
                return httpx.Response(404, json={"error": "no transcript"})
            return httpx.Response(200, json={"transcript_text": "ok"})
        return httpx.Response(500, json={"error": "unexpected"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = list_meetings_for_day(
        config,
        date(2026, 3, 7),
        timezone_name="America/Chicago",
        client=client,
        max_retries=0,
    )
    assert result == [
        MeetingCandidate(
            document_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            title="Included",
            started_at="2026-03-07T09:00:00-06:00",
            has_transcript=True,
            source_url="https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b04",
        )
    ]
    client.close()


def test_list_meetings_for_day_desktop_session_reimports_after_rejected_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _base_config(tmp_path, "desktop_session")
    monkeypatch.setattr("meeting_agent.retrieval.get_desktop_session_access_token", lambda: "stale-token")

    class _Creds:
        def __init__(self, access_token: str) -> None:
            self.access_token = access_token

    monkeypatch.setattr(
        "meeting_agent.retrieval.refresh_desktop_session_credentials",
        lambda client=None: _Creds("refreshed-token"),
    )
    monkeypatch.setattr(
        "meeting_agent.retrieval.import_desktop_session_credentials",
        lambda: _Creds("imported-token"),
    )

    seen_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("Authorization", ""))
        if request.headers.get("Authorization") != "Bearer imported-token":
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(
            200,
            json={
                "docs": [
                    {
                        "id": "29250e01-0751-4e02-9b24-f6d06f878b04",
                        "meeting_id": "29250e01-0751-4e02-9b24-f6d06f878b04",
                        "title": "Recovered",
                        "started_at": "2026-03-07T09:00:00-06:00",
                        "has_transcript": True,
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = list_meetings_for_day(
        config,
        date(2026, 3, 7),
        timezone_name="America/Chicago",
        client=client,
        max_retries=0,
    )

    assert [candidate.title for candidate in result] == ["Recovered"]
    assert seen_headers == [
        "Bearer stale-token",
        "Bearer refreshed-token",
        "Bearer imported-token",
    ]
    client.close()


def test_list_meetings_for_day_retries_next_endpoint_on_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _base_config(tmp_path, "token")
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/v1/get-documents":
            return httpx.Response(404, json={"error": "missing"})
        if request.url.path == "/v1/list-documents":
            return httpx.Response(
                200,
                json={
                    "documents": [
                        {
                            "id": "29250e01-0751-4e02-9b24-f6d06f878b04",
                            "meeting_id": "29250e01-0751-4e02-9b24-f6d06f878b04",
                            "started_at": "2026-03-07T09:00:00-06:00",
                            "has_transcript": True,
                        }
                    ]
                },
            )
        if request.url.path == "/v1/get-document-transcript":
            return httpx.Response(200, json={"transcript_text": "ok"})
        return httpx.Response(500, json={"error": "unexpected"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = list_meetings_for_day(
        config,
        date(2026, 3, 7),
        timezone_name="America/Chicago",
        client=client,
        max_retries=0,
    )
    assert len(result) == 1
    assert "/v1/get-documents" in seen_paths
    assert "/v1/list-documents" in seen_paths
    client.close()
