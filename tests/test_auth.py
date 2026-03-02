from pathlib import Path

import httpx
import pytest

from meeting_agent.auth import (
    DesktopSessionCredentials,
    get_desktop_session_access_token,
    get_default_desktop_session_path,
    import_desktop_session_credentials,
    parse_desktop_session_json,
    refresh_desktop_session_credentials,
)
from meeting_agent.errors import ConfigError, RetrievalError


def test_parse_desktop_session_json_prefers_workos_tokens() -> None:
    raw = """{
      "workos_tokens": "{\\"access_token\\":\\"a\\",\\"refresh_token\\":\\"r\\",\\"client_id\\":\\"c\\"}"
    }"""
    creds = parse_desktop_session_json(raw)
    assert creds is not None
    assert creds.access_token == "a"
    assert creds.refresh_token == "r"
    assert creds.client_id == "c"


def test_parse_desktop_session_json_falls_back_to_cognito() -> None:
    raw = """{
      "cognito_tokens": "{\\"access_token\\":\\"a2\\",\\"refresh_token\\":\\"r2\\"}"
    }"""
    creds = parse_desktop_session_json(raw)
    assert creds is not None
    assert creds.access_token == "a2"
    assert creds.refresh_token == "r2"


def test_import_desktop_session_credentials_reads_file_and_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_file = tmp_path / "granola-session.json"
    session_file.write_text('{"refresh_token":"r","access_token":"a","client_id":"c"}', encoding="utf-8")

    captured: dict[str, DesktopSessionCredentials] = {}

    def _save(creds: DesktopSessionCredentials) -> None:
        captured["creds"] = creds

    monkeypatch.setattr("meeting_agent.auth.save_keychain_credentials", _save)
    imported = import_desktop_session_credentials(session_file)

    assert imported.access_token == "a"
    assert captured["creds"].refresh_token == "r"


def test_import_desktop_session_credentials_invalid_file_raises(tmp_path: Path) -> None:
    session_file = tmp_path / "granola-session.json"
    session_file.write_text("not-json", encoding="utf-8")
    with pytest.raises(ConfigError, match="Could not parse"):
        import_desktop_session_credentials(session_file)


def test_get_default_desktop_session_path_is_absolute() -> None:
    assert get_default_desktop_session_path().is_absolute()


def test_get_desktop_session_access_token_auto_imports_when_keychain_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("meeting_agent.auth.get_keychain_credentials", lambda: None)
    monkeypatch.setattr(
        "meeting_agent.auth.import_desktop_session_credentials",
        lambda path=None: DesktopSessionCredentials(access_token="fresh", refresh_token="r", client_id="c"),
    )

    token = get_desktop_session_access_token()
    assert token == "fresh"


def test_get_desktop_session_access_token_raises_when_auto_import_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("meeting_agent.auth.get_keychain_credentials", lambda: None)

    def _raise_import(path=None):
        raise ConfigError("missing file")

    monkeypatch.setattr("meeting_agent.auth.import_desktop_session_credentials", _raise_import)
    with pytest.raises(RetrievalError, match="No desktop-session credentials found"):
        get_desktop_session_access_token()


def test_refresh_desktop_session_credentials_auto_imports_on_http_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "meeting_agent.auth.get_keychain_credentials",
        lambda: DesktopSessionCredentials(access_token="", refresh_token="old-r", client_id="c"),
    )
    monkeypatch.setattr(
        "meeting_agent.auth.import_desktop_session_credentials",
        lambda path=None: DesktopSessionCredentials(access_token="imported-token", refresh_token="r2", client_id="c"),
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad refresh"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    creds = refresh_desktop_session_credentials(client=client)
    client.close()
    assert creds.access_token == "imported-token"
