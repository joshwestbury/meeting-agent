import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
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
        client_id = _resolve_client_id(
            workos.get("client_id"),
            access_token=str(workos.get("access_token", "")),
        )
        return DesktopSessionCredentials(
            refresh_token=str(workos.get("refresh_token", "")),
            access_token=str(workos.get("access_token", "")),
            client_id=client_id,
        )

    cognito = _extract_embedded_json(parsed.get("cognito_tokens"))
    if cognito and isinstance(cognito.get("refresh_token"), str):
        client_id = _resolve_client_id(
            cognito.get("client_id"),
            access_token=str(cognito.get("access_token", "")),
        )
        return DesktopSessionCredentials(
            refresh_token=str(cognito.get("refresh_token", "")),
            access_token=str(cognito.get("access_token", "")),
            client_id=client_id,
        )

    refresh_token = parsed.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        client_id = _resolve_client_id(
            parsed.get("client_id"),
            access_token=str(parsed.get("access_token", "")),
        )
        return DesktopSessionCredentials(
            refresh_token=refresh_token,
            access_token=str(parsed.get("access_token", "")),
            client_id=client_id,
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
        client_id = _resolve_client_id(
            tokens.get("client_id"),
            access_token=str(tokens.get("access_token", "")),
        )
        credentials.append(
            DesktopSessionCredentials(
                refresh_token=str(tokens.get("refresh_token", "")),
                access_token=str(tokens.get("access_token", "")),
                client_id=client_id,
            )
        )
    return credentials


def import_desktop_session_credentials(path: Path | None = None) -> DesktopSessionCredentials:
    source_path = path or get_default_desktop_session_path()
    if not source_path.exists() and (path is not None or not _encrypted_storage_path(source_path).exists()):
        raise ConfigError(f"Granola desktop session file not found: {source_path}")

    creds = _choose_best_credentials(_load_desktop_session_credentials(source_path, include_encrypted=path is None))
    if path is None:
        creds = _choose_best_credentials([creds, *_load_stored_account_credentials(include_encrypted=True)])
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
                    _resolve_refresh_url(creds),
                    json={
                        "grant_type": "refresh_token",
                        "client_id": creds.client_id,
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
                if has_newer_encrypted_granola_storage():
                    message += (
                        ". Granola has newer encrypted desktop session files, but meeting-agent could not "
                        "read them from macOS Keychain. Approve access to `Granola Safe Storage` if prompted, "
                        "then run `meeting-agent auth-import`."
                    )
                elif imported and imported.access_token and is_access_token_expired(imported.access_token):
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

            new_refresh = payload.get("refreshToken") or payload.get("refresh_token")
            new_access = payload.get("accessToken") or payload.get("access_token")
            if not isinstance(new_access, str) or not new_access:
                raise RetrievalError(PARSE_ERROR, "Token refresh response missing accessToken")
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


def _load_desktop_session_credentials(
    path: Path,
    *,
    include_encrypted: bool,
) -> list[DesktopSessionCredentials]:
    credentials: list[DesktopSessionCredentials] = []
    for raw in _load_granola_storage_candidates(path, include_encrypted=include_encrypted):
        creds = parse_desktop_session_json(raw)
        if creds is not None:
            credentials.append(creds)
    return credentials


def _load_stored_account_credentials(*, include_encrypted: bool = False) -> list[DesktopSessionCredentials]:
    stored_accounts_path = get_default_stored_accounts_path()
    credentials: list[DesktopSessionCredentials] = []
    for raw in _load_granola_storage_candidates(stored_accounts_path, include_encrypted=include_encrypted):
        credentials.extend(parse_stored_accounts_json(raw))
    return credentials


def _load_granola_storage_candidates(path: Path, *, include_encrypted: bool) -> list[str]:
    candidates: list[tuple[float, str]] = []
    encrypted_path = _encrypted_storage_path(path)
    if include_encrypted and encrypted_path.exists():
        encrypted_raw = _read_encrypted_granola_storage(encrypted_path)
        if encrypted_raw is not None:
            candidates.append((_mtime(encrypted_path), encrypted_raw))
    if path.exists():
        try:
            candidates.append((_mtime(path), path.read_text(encoding="utf-8")))
        except OSError as exc:
            if not candidates:
                raise ConfigError(f"Could not read Granola desktop session file: {path}") from exc
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)

    deduped: list[str] = []
    for _, raw in candidates:
        if raw not in deduped:
            deduped.append(raw)
    return deduped


def _encrypted_storage_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.enc")


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


def _read_encrypted_granola_storage(path: Path) -> str | None:
    try:
        dek = _read_granola_storage_dek(path.with_name("storage.dek"))
        if dek is None:
            return None
        data = path.read_bytes()
        return _decrypt_granola_storage_payload(data, dek)
    except Exception:
        return None


def _read_granola_storage_dek(path: Path) -> bytes | None:
    if not path.exists() or os.uname().sysname.lower() != "darwin":
        return None
    encrypted = path.read_bytes()
    if not encrypted.startswith(b"v10"):
        return None
    password = _read_macos_safe_storage_password()
    if not password:
        return None

    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), b"saltysalt", 1003, dklen=16)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    padded = decryptor.update(encrypted[3:]) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    decoded = unpadder.update(padded) + unpadder.finalize()
    dek = base64.b64decode(decoded)
    if len(dek) != 32:
        return None
    return dek


def _read_macos_safe_storage_password() -> str | None:
    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            [
                "security",
                "find-generic-password",
                "-s",
                "Granola Safe Storage",
                "-a",
                "Granola Key",
                "-w",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        stdout, _ = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        if proc is not None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
        return None
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return stdout.rstrip("\n") or None


def _decrypt_granola_storage_payload(data: bytes, dek: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    iv_len = 12
    tag_len = 16
    if len(data) <= iv_len + tag_len:
        raise ValueError("Encrypted Granola storage payload is too short")
    iv = data[:iv_len]
    ciphertext = data[iv_len:-tag_len]
    tag = data[-tag_len:]
    return AESGCM(dek).decrypt(iv, ciphertext + tag, None).decode("utf-8")


def has_newer_encrypted_granola_storage() -> bool:
    for path in (get_default_desktop_session_path(), get_default_stored_accounts_path()):
        encrypted_path = _encrypted_storage_path(path)
        if encrypted_path.exists() and _mtime(encrypted_path) > _mtime(path):
            return True
    return False


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


def _resolve_client_id(raw_client_id: Any, *, access_token: str) -> str:
    if isinstance(raw_client_id, str) and raw_client_id:
        return raw_client_id
    claims = _decode_jwt_claims(access_token)
    if claims:
        issuer = claims.get("iss")
        if isinstance(issuer, str):
            inferred = issuer.rstrip("/").rsplit("/", 1)[-1]
            if inferred.startswith("client_"):
                return inferred
    return DEFAULT_CLIENT_ID


def _resolve_refresh_url(creds: DesktopSessionCredentials) -> str:
    claims = _decode_jwt_claims(creds.access_token)
    if claims:
        issuer = claims.get("iss")
        if isinstance(issuer, str) and "/user_management/" in issuer:
            base_url = issuer.split("/user_management/", 1)[0].rstrip("/")
            if base_url.startswith("http://") or base_url.startswith("https://"):
                return f"{base_url}/user_management/authenticate"
    return WORKOS_AUTH_URL


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
