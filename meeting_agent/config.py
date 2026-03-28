import os
import warnings
from pathlib import Path
import tempfile
import tomllib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from meeting_agent.errors import ConfigError


AuthMode = Literal["token", "cookie", "manual_export", "desktop_session"]
LlmMode = Literal["local", "none"]
LlmRuntime = Literal["llama.cpp"]


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vault_root: Path
    staging_root: Path
    default_folder: str | None = None
    timezone: str = "local"
    auth_mode: AuthMode
    auth_token_env: str | None = Field(default="MEETING_AGENT_TOKEN")
    cookie_file: Path | None = None
    llm_mode: LlmMode = "local"
    llm_runtime: LlmRuntime = "llama.cpp"
    llm_model: str = "LiquidAI/LFM2-2.6B-Transcript-GGUF"
    llm_model_variant: str = "Q4_K_M"
    llm_server_url: str = "http://127.0.0.1:8080"
    model_cache_dir: Path = Field(
        default_factory=lambda: Path.home() / ".cache" / "meeting-agent" / "models"
    )

    @field_validator("vault_root", "staging_root", "cookie_file", "model_cache_dir", mode="before")
    @classmethod
    def _expand_path(cls, value: object) -> object:
        if value is None:
            return value
        if isinstance(value, Path):
            return value.expanduser()
        if isinstance(value, str):
            return Path(value).expanduser()
        return value


def get_config_path() -> Path:
    return Path.home() / ".config" / "meeting-agent" / "config.toml"


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _to_toml(config: AppConfig) -> str:
    lines: list[str] = [
        f"vault_root = {_quote(str(config.vault_root))}",
        f"staging_root = {_quote(str(config.staging_root))}",
    ]
    if config.default_folder is not None:
        lines.append(f"default_folder = {_quote(config.default_folder)}")
    else:
        lines.append("default_folder = \"\"")
    lines.extend(
        [
            f"timezone = {_quote(config.timezone)}",
            f"auth_mode = {_quote(config.auth_mode)}",
            f"auth_token_env = {_quote(config.auth_token_env or '')}",
            f"cookie_file = {_quote(str(config.cookie_file) if config.cookie_file else '')}",
            f"llm_mode = {_quote(config.llm_mode)}",
            f"llm_runtime = {_quote(config.llm_runtime)}",
            f"llm_model = {_quote(config.llm_model)}",
            f"llm_model_variant = {_quote(config.llm_model_variant)}",
            f"llm_server_url = {_quote(config.llm_server_url)}",
            f"model_cache_dir = {_quote(str(config.model_cache_dir))}",
        ]
    )
    return "\n".join(lines) + "\n"


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    config_path = path or get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=config_path.parent,
        prefix=f"{config_path.name}.",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as tmp_file:
        tmp_file.write(_to_toml(config))
        tmp_name = tmp_file.name

    Path(tmp_name).replace(config_path)
    return config_path


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or get_config_path()
    if not config_path.exists():
        raise ConfigError(f"Config not found: {config_path}")

    try:
        with config_path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid config file: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read config file: {config_path}") from exc

    default_folder = raw.get("default_folder") or None
    cookie_file = raw.get("cookie_file") or None
    auth_token_env = raw.get("auth_token_env") or None

    try:
        return AppConfig(
            vault_root=raw["vault_root"],
            staging_root=raw["staging_root"],
            default_folder=default_folder,
            timezone=raw.get("timezone", "local"),
            auth_mode=raw["auth_mode"],
            auth_token_env=auth_token_env,
            cookie_file=cookie_file,
            llm_mode=raw.get("llm_mode", "local"),
            llm_runtime=raw.get("llm_runtime", "llama.cpp"),
            llm_model=raw.get("llm_model", "LiquidAI/LFM2-2.6B-Transcript-GGUF"),
            llm_model_variant=raw.get("llm_model_variant", "Q4_K_M"),
            llm_server_url=raw.get("llm_server_url", "http://127.0.0.1:8080"),
            model_cache_dir=raw.get("model_cache_dir", "~/.cache/meeting-agent/models"),
        )
    except KeyError as exc:
        raise ConfigError(f"Missing required config key: {exc.args[0]}") from exc
    except Exception as exc:
        raise ConfigError(f"Invalid config file: {exc}") from exc


def validate_init_config(config: AppConfig) -> None:
    if not config.vault_root.exists() or not config.vault_root.is_dir():
        raise ConfigError(f"vault_root does not exist or is not a directory: {config.vault_root}")
    if not os.access(config.vault_root, os.W_OK):
        raise ConfigError(f"vault_root is not writable: {config.vault_root}")

    try:
        config.staging_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"staging_root cannot be created: {config.staging_root}") from exc
    if not config.staging_root.is_dir() or not os.access(config.staging_root, os.W_OK):
        raise ConfigError(f"staging_root is not writable: {config.staging_root}")

    if config.auth_mode == "token":
        env_name = (config.auth_token_env or "").strip()
        if not env_name:
            raise ConfigError("token auth_mode requires auth_token_env")
        if not os.environ.get(env_name):
            raise ConfigError(
                f"token auth_mode requires environment variable {env_name} to be set"
            )
    elif config.auth_mode == "cookie":
        if config.cookie_file is None:
            raise ConfigError("cookie auth_mode requires cookie_file")
        if not config.cookie_file.exists() or not config.cookie_file.is_file():
            raise ConfigError(f"cookie_file not found: {config.cookie_file}")
    elif config.auth_mode == "desktop_session":
        # Desktop-session mode validates connectivity at auth-check/process time.
        pass

    if config.llm_mode == "local":
        if not config.llm_runtime:
            raise ConfigError("local llm_mode requires llm_runtime")
        if not config.llm_model.strip():
            raise ConfigError("local llm_mode requires llm_model")
        if not config.llm_model_variant.strip():
            raise ConfigError("local llm_mode requires llm_model_variant")
        if not config.llm_server_url.strip():
            raise ConfigError("local llm_mode requires llm_server_url")


def load_and_validate_startup_config(path: Path | None = None) -> AppConfig:
    config_path = path or get_config_path()
    config = load_config(path)
    if config.llm_mode == "none":
        config = config.model_copy(update={"llm_mode": "local"})
        save_config(config, path=config_path)
        warnings.warn(
            "llm_mode was 'none' in config; updated to 'local' and saved.",
            UserWarning,
            stacklevel=2,
        )
    validate_init_config(config)
    return config
