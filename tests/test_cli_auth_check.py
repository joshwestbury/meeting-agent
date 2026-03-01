from pathlib import Path

from typer.testing import CliRunner

from meeting_agent.cli import app
from meeting_agent.config import AppConfig
from meeting_agent.errors import RetrievalError
from meeting_agent.retrieval import AUTH_REQUIRED, RetrievalResult


def _config(tmp_path: Path, auth_mode: str) -> AppConfig:
    vault_root = tmp_path / "vault"
    vault_root.mkdir(exist_ok=True)
    return AppConfig(
        vault_root=vault_root,
        staging_root=tmp_path / "staging",
        auth_mode=auth_mode,  # type: ignore[arg-type]
        auth_token_env="MEETING_AGENT_TOKEN",
    )


def test_auth_check_rejects_manual_export_mode(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path, "manual_export"))

    result = runner.invoke(app, ["auth-check", "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04"])

    assert result.exit_code == 2
    assert "requires remote auth mode" in result.output


def test_auth_check_success_reports_meeting_details(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path, "token"))

    def _mock_retrieve(_: str, __: AppConfig, max_retries: int = 0) -> RetrievalResult:
        assert max_retries == 0
        return RetrievalResult(
            granola_id="g-1",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            title="Sync",
            started_at=None,
            attendees=[],
            transcript_text="abc",
            raw_payload={},
        )

    monkeypatch.setattr("meeting_agent.cli.retrieve_transcript", _mock_retrieve)

    result = runner.invoke(app, ["auth-check", "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04"])

    assert result.exit_code == 0
    assert "Granola auth-check succeeded." in result.output
    assert "meeting_id:" in result.output
    assert "transcript_chars: 3" in result.output


def test_auth_check_surfaces_retrieval_error_code(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path, "token"))

    def _mock_retrieve(_: str, __: AppConfig, max_retries: int = 0) -> RetrievalResult:
        raise RetrievalError(AUTH_REQUIRED, "missing token")

    monkeypatch.setattr("meeting_agent.cli.retrieve_transcript", _mock_retrieve)

    result = runner.invoke(app, ["auth-check", "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04"])

    assert result.exit_code == 2
    assert "Granola auth-check failed [AUTH_REQUIRED]" in result.output
