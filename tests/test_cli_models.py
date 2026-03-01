from pathlib import Path

from typer.testing import CliRunner

from meeting_agent.cli import app
from meeting_agent.config import AppConfig


def _config(tmp_path: Path) -> AppConfig:
    vault_root = tmp_path / "vault"
    vault_root.mkdir(exist_ok=True)
    return AppConfig(
        vault_root=vault_root,
        staging_root=tmp_path / "staging",
        auth_mode="manual_export",
        llm_model="LiquidAI/LFM2-2.6B-Transcript-GGUF",
        llm_model_variant="Q4_K_M",
        llm_server_url="http://127.0.0.1:8080",
        model_cache_dir=tmp_path / "models",
    )


def test_models_pull_uses_config_defaults(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))

    captured: dict[str, object] = {}

    class _Result:
        downloaded = True
        output_path = Path("/tmp/model.gguf")

    def _mock_pull_model(**kwargs):
        captured.update(kwargs)
        return _Result()

    monkeypatch.setattr("meeting_agent.cli.models.pull_model", _mock_pull_model)

    result = runner.invoke(app, ["models", "pull"])
    assert result.exit_code == 0
    assert "Pulling model:" in result.output
    assert "Downloaded:" in result.output
    assert captured["repo_id"] == "LiquidAI/LFM2-2.6B-Transcript-GGUF"
    assert captured["variant"] == "Q4_K_M"


def test_models_doctor_outputs_actionable_recommendations(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))

    class _Report:
        runtime_installed = False
        runtime_path = None
        model_present = False
        model_path = Path("/tmp/missing.gguf")
        server_reachable = False

    monkeypatch.setattr("meeting_agent.cli.models.run_models_doctor", lambda **_kwargs: _Report())

    result = runner.invoke(app, ["models", "doctor"])
    assert result.exit_code == 0
    assert "runtime_installed: False" in result.output
    assert "Action: install llama.cpp" in result.output
    assert "Action: run `meeting-agent models pull`" in result.output
    assert "Action: start local server" in result.output


def test_models_list_shows_installed_paths(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "meeting_agent.cli.models.list_installed_models",
        lambda _cache: [Path("/tmp/a.gguf"), Path("/tmp/b.gguf")],
    )

    result = runner.invoke(app, ["models", "list"])
    assert result.exit_code == 0
    assert "Installed models:" in result.output
    assert "/tmp/a.gguf" in result.output
    assert "/tmp/b.gguf" in result.output
