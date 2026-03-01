from pathlib import Path

import pytest

from meeting_agent.config import (
    AppConfig,
    get_config_path,
    load_and_validate_startup_config,
    save_config,
    validate_init_config,
)
from meeting_agent.errors import ConfigError


def test_get_config_path_uses_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert get_config_path() == tmp_path / ".config" / "meeting-agent" / "config.toml"


def test_save_and_load_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    staging_root = tmp_path / "staging"
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")

    config = AppConfig(
        vault_root=vault_root,
        staging_root=staging_root,
        default_folder="Inbox/Meetings",
        timezone="local",
        auth_mode="token",
        auth_token_env="MEETING_AGENT_TOKEN",
    )
    save_config(config, tmp_path / "config.toml")

    loaded = load_and_validate_startup_config(tmp_path / "config.toml")

    assert loaded.vault_root == vault_root
    assert loaded.staging_root == staging_root
    assert loaded.default_folder == "Inbox/Meetings"
    assert loaded.auth_mode == "token"
    assert loaded.auth_token_env == "MEETING_AGENT_TOKEN"


def test_validate_init_requires_existing_vault(tmp_path: Path) -> None:
    config = AppConfig(
        vault_root=tmp_path / "missing-vault",
        staging_root=tmp_path / "staging",
        auth_mode="manual_export",
    )
    with pytest.raises(ConfigError, match="vault_root"):
        validate_init_config(config)


def test_validate_token_auth_requires_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.delenv("MEETING_AGENT_TOKEN", raising=False)

    config = AppConfig(
        vault_root=vault_root,
        staging_root=tmp_path / "staging",
        auth_mode="token",
        auth_token_env="MEETING_AGENT_TOKEN",
    )
    with pytest.raises(ConfigError, match="MEETING_AGENT_TOKEN"):
        validate_init_config(config)


def test_validate_cookie_auth_requires_cookie_file(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    config = AppConfig(
        vault_root=vault_root,
        staging_root=tmp_path / "staging",
        auth_mode="cookie",
        cookie_file=tmp_path / "missing-cookie.txt",
    )
    with pytest.raises(ConfigError, match="cookie_file"):
        validate_init_config(config)


def test_load_config_missing_required_key(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('vault_root = "/tmp/vault"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="Missing required config key"):
        load_and_validate_startup_config(path)


def test_load_config_invalid_auth_mode(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                f'vault_root = "{vault_root}"',
                f'staging_root = "{tmp_path / "staging"}"',
                'auth_mode = "invalid_mode"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Invalid config file"):
        load_and_validate_startup_config(path)


def test_load_config_malformed_toml_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('vault_root = "/tmp/vault"\nauth_mode = "manual_export"\n[broken\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="Invalid config file"):
        load_and_validate_startup_config(path)


def test_load_config_expands_tilde_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    vault_root = home / "vault"
    vault_root.mkdir()
    cookie_file = home / "cookies.txt"
    cookie_file.write_text("cookie=data", encoding="utf-8")
    staging_root = home / "staging"

    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                'vault_root = "~/vault"',
                'staging_root = "~/staging"',
                'auth_mode = "cookie"',
                'cookie_file = "~/cookies.txt"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = load_and_validate_startup_config(path)

    assert loaded.vault_root == vault_root
    assert loaded.staging_root == staging_root
    assert loaded.cookie_file == cookie_file


def test_save_config_replace_failure_preserves_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")

    config_path = tmp_path / "config.toml"
    config_path.write_text("original-content\n", encoding="utf-8")

    config = AppConfig(
        vault_root=vault_root,
        staging_root=tmp_path / "staging",
        auth_mode="token",
        auth_token_env="MEETING_AGENT_TOKEN",
    )

    original_replace = Path.replace

    def _raise_replace(self: Path, target: Path) -> Path:
        if self.name.endswith(".tmp") and target == config_path:
            raise OSError("replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", _raise_replace, raising=True)

    with pytest.raises(OSError, match="replace failed"):
        save_config(config, config_path)

    assert config_path.read_text(encoding="utf-8") == "original-content\n"


def test_validate_local_llm_requires_non_empty_model(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    config = AppConfig(
        vault_root=vault_root,
        staging_root=tmp_path / "staging",
        auth_mode="manual_export",
        llm_mode="local",
        llm_model="   ",
    )
    with pytest.raises(ConfigError, match="llm_model"):
        validate_init_config(config)


def test_model_cache_dir_default_expands_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    vault_root = home / "vault"
    vault_root.mkdir()
    config = AppConfig(
        vault_root=vault_root,
        staging_root=home / "staging",
        auth_mode="manual_export",
    )
    assert config.model_cache_dir == home / ".cache" / "meeting-agent" / "models"
