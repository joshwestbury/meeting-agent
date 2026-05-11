import base64
import json
import os
from pathlib import Path
import time
from typing import Any

import httpx
import keyring
from pydantic import BaseModel, ConfigDict

from meeting_agent.errors import ConfigError, RetrievalError, StateError

AUTH_REQUIRED = "AUTH_REQUIRED"
NETWORK_ERROR = "NETWORK_ERROR"
PARSE_ERROR = "PARSE_ERROR"


WORKOS_AUTH_URL = "https://api.workos.com/user_management/authenticate"
KEYCHAIN_SERVICE = "com.meeting-agent.granola"
KEYCHAIN_ACCOUNT = "desktop_session"
DEFAULT_CLIENT_ID = "client_GranolaMac"


class DesktopSessionCredentials(BaseModel):
    model_config = ConfigDict(extra="ignore")

    refresh_token: str = ""
    access_token: str = ""
    client_id: str = DEFAULT_CLIENT_ID


def get_default_desktop_session_path() -> Path:
    home = Path.home()
    system = os.uname().sysname.lower()
    if "darwin" in system:
        return home / "Library" / "Application Support" / "Granola" / "supabase.json"
    if "linux" in system:
        return home / ".config" / "granola" / "supabase.json"
    return home / "AppData" / "Roaming" / "Granola" / "supabase.json"


def get_default_stored_accounts_path() -> Path:
    return get_default_desktop_session_path().with_name("stored-accounts.json")


def parse_desktop_session_json(raw_json: str) -> DesktopSessionCredentials | None:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    workos = _extract_embedded_json(parsed.get("workos_tokens"))
    if workos and isinstance(workos.get("access_token"), str):
        return DesktopSessionCredentials(
            refresh_token=str(workos.get("refresh_token", "")),
            access_token=str(workos.get("access_token", "")),
            client_id=str(workos.get("client_id", DEFAULT_CLIENT_ID)),
        )

    cognito = _extract_embedded_json(parsed.get("cognito_tokens"))
    if cognito and isinstance(cognito.get("refresh_token"), str):
        return DesktopSessionCredentials(
            refresh_token=str(cognito.get("refresh_token", "")),
            access_token=str(cognito.get("access_token", "")),
            client_id=str(cognito.get("client_id", DEFAULT_CLIENT_ID)),
        )

    refresh_token = parsed.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        return DesktopSessionCredentials(
            refresh_token=refresh_token,
            access_token=str(parsed.get("access_token", "")),
            client_id=str(parsed.get("client_id", DEFAULT_CLIENT_ID)),
        )
    return None


def parse_stored_accounts_json(raw_json: str) -> list[DesktopSessionCredentials]:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict):
        return []

    accounts = parsed.get("accounts")
    if isinstance(accounts, str):
        try:
            accounts = json.loads(accounts)
        except json.JSONDecodeError:
            return []
    if not isinstance(accounts, list):
        return []

    credentials: list[DesktopSessionCredentials] = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        tokens = _extract_embedded_json(account.get("tokens"))
        if not tokens or not isinstance(tokens.get("access_token"), str):
            continue
        credentials.append(
            DesktopSessionCredentials(
                refresh_token=str(tokens.get("refresh_token", "")),
                access_token=str(tokens.get("access_token", "")),
                client_id=str(tokens.get("client_id", DEFAULT_CLIENT_ID)),
            )
        )
    return credentials


def import_desktop_session_credentials(path: Path | None = None) -> DesktopSessionCredentials:
    source_path = path or get_default_desktop_session_path()
    if not source_path.exists():
        raise ConfigError(f"Granola desktop session file not found: {source_path}")
    try:
        raw = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not read Granola desktop session file: {source_path}") from exc

    creds = parse_desktop_session_json(raw)
    if path is None:
        creds = _choose_best_credentials([creds, *_load_stored_account_credentials()])
    if creds is None:
        raise ConfigError("Could not parse desktop session credentials from Granola file")

    save_keychain_credentials(creds)
    return creds


def is_access_token_expired(access_token: str, *, now: float | None = None) -> bool:
    """Return True when a JWT access token carries an expired `exp` claim."""
    claims = _decode_jwt_claims(access_token)
    if claims is None:
        return False
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return exp <= (time.time() if now is None else now)


def _access_token_exp(access_token: str) -> float | None:
    claims = _decode_jwt_claims(access_token)
    if claims is None:
        return None
    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        return float(exp)
    return None


def _choose_best_credentials(
    candidates: list[DesktopSessionCredentials | None],
) -> DesktopSessionCredentials | None:
    available = [candidate for candidate in candidates if candidate is not None]
    if not available:
        return None
    unexpired = [
        candidate
        for candidate in available
        if candidate.access_token and not is_access_token_expired(candidate.access_token)
    ]
    if unexpired:
        return max(unexpired, key=lambda candidate: _access_token_exp(candidate.access_token) or 0)
    return available[0]


def get_keychain_credentials() -> DesktopSessionCredentials | None:
    try:
        stored = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except Exception as exc:  # pragma: no cover - backend dependent
        raise ConfigError(f"Keychain read failed: {exc}") from exc
    if not stored:
        return None
    try:
        parsed = json.loads(stored)
        return DesktopSessionCredentials.model_validate(parsed)
    except Exception as exc:
        raise ConfigError("Stored keychain credentials are invalid") from exc


def save_keychain_credentials(creds: DesktopSessionCredentials) -> None:
    try:
        keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, creds.model_dump_json())
    except Exception as exc:  # pragma: no cover - backend dependent
        raise ConfigError(f"Keychain write failed: {exc}") from exc


def get_desktop_session_access_token() -> str:
    creds = get_keychain_credentials()
    if creds is None:
        creds = _auto_import_desktop_session_credentials()
        if creds is None:
            raise RetrievalError(
                AUTH_REQUIRED,
                "No desktop-session credentials found. Run `meeting-agent auth-import` first.",
            )
    if creds.access_token and not is_access_token_expired(creds.access_token):
        return creds.access_token
    try:
        refreshed = refresh_desktop_session_credentials()
        return refreshed.access_token
    except RetrievalError:
        imported = _auto_import_desktop_session_credentials()
        if imported and imported.access_token and not is_access_token_expired(imported.access_token):
            return imported.access_token
        raise


def refresh_desktop_session_credentials(
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = 5.0,
) -> DesktopSessionCredentials:
    with _refresh_lock(timeout_seconds=timeout_seconds):
        creds = get_keychain_credentials()
        if creds is None:
            raise RetrievalError(AUTH_REQUIRED, "No stored desktop-session credentials to refresh.")
        if not creds.refresh_token or not creds.client_id:
            raise RetrievalError(AUTH_REQUIRED, "Stored credentials missing refresh token or client id.")

        created_client = client is None
        http_client = client or httpx.Client()
        try:
            try:
                response = http_client.post(
                    WORKOS_AUTH_URL,
                    json={
                        "client_id": creds.client_id,
                        "grant_type": "refresh_token",
                        "refresh_token": creds.refresh_token,
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=20.0,
                )
            except httpx.TransportError as exc:
                raise RetrievalError(NETWORK_ERROR, f"Desktop-session token refresh failed: {exc}") from exc

            if response.status_code >= 400:
                imported = _auto_import_desktop_session_credentials()
                if imported and imported.access_token and not is_access_token_expired(imported.access_token):
                    return imported
                message = f"Desktop-session token refresh rejected: HTTP {response.status_code}"
                if imported and imported.access_token and is_access_token_expired(imported.access_token):
                    message += (
                        ". Granola desktop session file also contains an expired access token; "
                        "open Granola desktop and sign in again, then run `meeting-agent auth-import`."
                    )
                raise RetrievalError(
                    AUTH_REQUIRED,
                    message,
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise RetrievalError(PARSE_ERROR, "Token refresh response was not valid JSON") from exc
            if not isinstance(payload, dict):
                raise RetrievalError(PARSE_ERROR, "Token refresh response must be a JSON object")

            new_refresh = payload.get("refresh_token")
            new_access = payload.get("access_token")
            if not isinstance(new_access, str) or not new_access:
                raise RetrievalError(PARSE_ERROR, "Token refresh response missing access_token")
            if is_access_token_expired(new_access):
                raise RetrievalError(AUTH_REQUIRED, "Token refresh returned an expired access token.")
            new_creds = DesktopSessionCredentials(
                refresh_token=str(new_refresh or creds.refresh_token),
                access_token=new_access,
                client_id=creds.client_id,
            )
            save_keychain_credentials(new_creds)
            return new_creds
        finally:
            if created_client:
                http_client.close()


def _auto_import_desktop_session_credentials() -> DesktopSessionCredentials | None:
    try:
        return import_desktop_session_credentials()
    except ConfigError:
        return None


def _load_stored_account_credentials() -> list[DesktopSessionCredentials]:
    stored_accounts_path = get_default_stored_accounts_path()
    if not stored_accounts_path.exists():
        return []
    try:
        raw = stored_accounts_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_stored_accounts_json(raw)


def _extract_embedded_json(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _decode_jwt_claims(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        claims = json.loads(decoded)
    except Exception:
        return None
    if isinstance(claims, dict):
        return claims
    return None


from contextlib import contextmanager


@contextmanager
def _refresh_lock(timeout_seconds: float):
    lock_path = Path.home() / ".config" / "meeting-agent" / "auth-refresh.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if (time.monotonic() - start) >= timeout_seconds:
                raise StateError(f"Could not acquire auth refresh lock: {lock_path}")
            time.sleep(0.02)

    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
        yield
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            lock_path.unlink(missing_ok=True)
        except OSError as exc:
            raise StateError(f"Could not release auth refresh lock: {lock_path}") from exc
