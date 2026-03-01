from pathlib import Path

import pytest

from meeting_agent.auth import (
    DesktopSessionCredentials,
    get_default_desktop_session_path,
    import_desktop_session_credentials,
    parse_desktop_session_json,
)
from meeting_agent.errors import ConfigError


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
