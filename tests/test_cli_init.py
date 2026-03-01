from pathlib import Path

from typer.testing import CliRunner

from meeting_agent.cli import app


def test_cli_init_success_manual_export(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    staging_root = tmp_path / "staging"

    user_input = "\n".join(
        [
            str(vault_root),
            str(staging_root),
            "Inbox/Meetings",
            "local",
            "manual_export",
        ]
    ) + "\n"

    result = runner.invoke(app, ["init"], input=user_input)

    assert result.exit_code == 0
    assert "Config written:" in result.output
    assert "Startup validation passed." in result.output
    config_path = home / ".config" / "meeting-agent" / "config.toml"
    assert config_path.exists()
    assert 'auth_mode = "manual_export"' in config_path.read_text(encoding="utf-8")


def test_cli_init_invalid_auth_mode_exits(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    staging_root = tmp_path / "staging"

    user_input = "\n".join(
        [
            str(vault_root),
            str(staging_root),
            "",
            "local",
            "bad_mode",
        ]
    ) + "\n"

    result = runner.invoke(app, ["init"], input=user_input)

    assert result.exit_code == 2
    assert "Auth mode must be one of" in result.output


def test_cli_startup_guard_without_config_shows_guidance(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    result = runner.invoke(app, [])

    assert result.exit_code == 2
    assert "Configuration error [config]:" in result.output
    assert "Run `meeting-agent init`" in result.output


def test_cli_init_bypasses_startup_guard(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    staging_root = tmp_path / "staging"
    token_env_name = "MY_TEST_TOKEN"
    monkeypatch.setenv(token_env_name, "secret")

    user_input = "\n".join(
        [
            str(vault_root),
            str(staging_root),
            "",
            "local",
            "token",
            token_env_name,
        ]
    ) + "\n"

    result = runner.invoke(app, ["init"], input=user_input)

    assert result.exit_code == 0
    assert "Startup validation passed." in result.output
