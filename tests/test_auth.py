import base64
import json
from pathlib import Path
import time

import httpx
import pytest

from meeting_agent.auth import (
    DesktopSessionCredentials,
    get_desktop_session_access_token,
    get_default_desktop_session_path,
    import_desktop_session_credentials,
    is_access_token_expired,
    parse_desktop_session_json,
    parse_stored_accounts_json,
    refresh_desktop_session_credentials,
)
from meeting_agent.errors import ConfigError, RetrievalError


def _jwt_with_exp(exp: int) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"{header}.{payload}."


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


def test_parse_desktop_session_json_derives_client_id_from_access_token_issuer() -> None:
    token = (
        "eyJhbGciOiJub25lIn0."
        "eyJpc3MiOiJodHRwczovL2F1dGguZ3Jhbm9sYS5haS91c2VyX21hbmFnZW1lbnQvY2xpZW50XzAxQUJDIn0."
    )
    raw = json.dumps(
        {
            "workos_tokens": json.dumps(
                {
                    "access_token": token,
                    "refresh_token": "r",
                }
            )
        }
    )

    creds = parse_desktop_session_json(raw)

    assert creds is not None
    assert creds.client_id == "client_01ABC"


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


def test_parse_stored_accounts_json_extracts_account_tokens() -> None:
    raw = json.dumps(
        {
            "accounts": json.dumps(
                [
                    {
                        "tokens": json.dumps(
                            {
                                "access_token": "a",
                                "refresh_token": "r",
                            }
                        )
                    }
                ]
            )
        }
    )

    creds = parse_stored_accounts_json(raw)

    assert len(creds) == 1
    assert creds[0].access_token == "a"
    assert creds[0].refresh_token == "r"


def test_parse_stored_accounts_json_derives_client_id_from_access_token_issuer() -> None:
    token = (
        "eyJhbGciOiJub25lIn0."
        "eyJpc3MiOiJodHRwczovL2F1dGguZ3Jhbm9sYS5haS91c2VyX21hbmFnZW1lbnQvY2xpZW50XzAxREVGIn0."
    )
    raw = json.dumps(
        {
            "accounts": json.dumps(
                [
                    {
                        "tokens": json.dumps(
                            {
                                "access_token": token,
                                "refresh_token": "r",
                            }
                        )
                    }
                ]
            )
        }
    )

    creds = parse_stored_accounts_json(raw)

    assert len(creds) == 1
    assert creds[0].client_id == "client_01DEF"


def test_import_desktop_session_credentials_prefers_fresh_stored_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    granola_dir = home / "Library" / "Application Support" / "Granola"
    granola_dir.mkdir(parents=True)
    expired = _jwt_with_exp(int(time.time()) - 60)
    fresh = _jwt_with_exp(int(time.time()) + 3600)
    (granola_dir / "supabase.json").write_text(
        json.dumps({"workos_tokens": json.dumps({"access_token": expired, "refresh_token": "old-r"})}),
        encoding="utf-8",
    )
    (granola_dir / "stored-accounts.json").write_text(
        json.dumps(
            {
                "accounts": json.dumps(
                    [
                        {
                            "tokens": json.dumps(
                                {
                                    "access_token": fresh,
                                    "refresh_token": "fresh-r",
                                }
                            )
                        }
                    ]
                )
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, DesktopSessionCredentials] = {}
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("meeting_agent.auth.save_keychain_credentials", lambda creds: captured.setdefault("creds", creds))

    imported = import_desktop_session_credentials()

    assert imported.access_token == fresh
    assert imported.refresh_token == "fresh-r"
    assert captured["creds"].access_token == fresh


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


def test_get_desktop_session_access_token_refreshes_expired_stored_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired = _jwt_with_exp(int(time.time()) - 60)
    fresh = _jwt_with_exp(int(time.time()) + 3600)
    monkeypatch.setattr(
        "meeting_agent.auth.get_keychain_credentials",
        lambda: DesktopSessionCredentials(access_token=expired, refresh_token="r", client_id="c"),
    )
    monkeypatch.setattr(
        "meeting_agent.auth.refresh_desktop_session_credentials",
        lambda: DesktopSessionCredentials(access_token=fresh, refresh_token="r", client_id="c"),
    )

    token = get_desktop_session_access_token()

    assert token == fresh


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
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


def test_refresh_desktop_session_credentials_uses_workos_refresh_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    access_token = (
        "eyJhbGciOiJub25lIn0."
        "eyJpc3MiOiJodHRwczovL2F1dGguZ3Jhbm9sYS5haS91c2VyX21hbmFnZW1lbnQvY2xpZW50LWMifQ."
    )
    monkeypatch.setattr(
        "meeting_agent.auth.get_keychain_credentials",
        lambda: DesktopSessionCredentials(
            access_token=access_token,
            refresh_token="old-refresh",
            client_id="client-c",
        ),
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "meeting_agent.auth.save_keychain_credentials",
        lambda creds: captured.setdefault("creds", creds),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "accessToken": "new-access",
                "refreshToken": "new-refresh",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    creds = refresh_desktop_session_credentials(client=client)
    client.close()

    assert captured["url"] == "https://auth.granola.ai/user_management/authenticate"
    assert captured["path"] == "/user_management/authenticate"
    assert captured["body"] == {
        "grant_type": "refresh_token",
        "client_id": "client-c",
        "refresh_token": "old-refresh",
    }
    assert creds.access_token == "new-access"
    assert creds.refresh_token == "new-refresh"
    assert captured["creds"] == creds


def test_is_access_token_expired_reads_jwt_exp_claim() -> None:
    assert is_access_token_expired(_jwt_with_exp(99), now=100)
    assert not is_access_token_expired(_jwt_with_exp(101), now=100)
    assert not is_access_token_expired("opaque-token", now=100)


def test_refresh_desktop_session_credentials_rejects_expired_auto_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    expired = _jwt_with_exp(int(time.time()) - 60)
    monkeypatch.setattr(
        "meeting_agent.auth.get_keychain_credentials",
        lambda: DesktopSessionCredentials(access_token="", refresh_token="old-r", client_id="c"),
    )
    monkeypatch.setattr(
        "meeting_agent.auth.import_desktop_session_credentials",
        lambda path=None: DesktopSessionCredentials(access_token=expired, refresh_token="r2", client_id="c"),
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad refresh"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RetrievalError, match="Desktop-session token refresh rejected"):
        refresh_desktop_session_credentials(client=client)
    client.close()
