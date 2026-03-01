from pathlib import Path

from typer.testing import CliRunner

from meeting_agent.auth import DesktopSessionCredentials
from meeting_agent.cli import app


def test_cli_auth_import_success(monkeypatch) -> None:
    runner = CliRunner()

    def _import(path=None):
        return DesktopSessionCredentials(
            refresh_token="r",
            access_token="a",
            client_id="client_GranolaMac",
        )

    monkeypatch.setattr("meeting_agent.cli.import_desktop_session_credentials", _import)
    result = runner.invoke(app, ["auth-import"])

    assert result.exit_code == 0
    assert "Desktop-session credentials imported." in result.output
    assert "has_access_token: True" in result.output


def test_cli_auth_import_passes_session_path(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    expected = tmp_path / "session.json"
    seen = {"path": None}

    def _import(path=None):
        seen["path"] = path
        return DesktopSessionCredentials(
            refresh_token="r",
            access_token="a",
            client_id="client_GranolaMac",
        )

    monkeypatch.setattr("meeting_agent.cli.import_desktop_session_credentials", _import)
    result = runner.invoke(app, ["auth-import", "--session-path", str(expected)])

    assert result.exit_code == 0
    assert seen["path"] == expected
