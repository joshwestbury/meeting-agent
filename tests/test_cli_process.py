from pathlib import Path

from typer.testing import CliRunner

from meeting_agent.cli import app
from meeting_agent.config import AppConfig
from meeting_agent.retrieval import RetrievalResult
from meeting_agent.state import StateEntry


def _config(tmp_path: Path) -> AppConfig:
    vault_root = tmp_path / "vault"
    vault_root.mkdir(exist_ok=True)
    return AppConfig(
        vault_root=vault_root,
        staging_root=tmp_path / "staging",
        default_folder="Inbox/Meetings/",
        timezone="local",
        auth_mode="manual_export",
        llm_mode="none",
    )


def test_process_new_not_implemented(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))

    result = runner.invoke(app, ["process", "--new"])

    assert result.exit_code == 3
    assert "not implemented yet" in result.output


def test_process_dry_run_no_llm_outputs_preview(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))

    def _mock_retrieve(_: str, __: AppConfig, client=None, max_retries: int = 2) -> RetrievalResult:
        return RetrievalResult(
            granola_id="g1",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            title="Weekly Sync",
            started_at="2026-03-01T09:12:00-06:00",
            attendees=[],
            transcript_text="hello world",
            raw_payload={},
        )

    monkeypatch.setattr("meeting_agent.cli.retrieve_transcript", _mock_retrieve)

    result = runner.invoke(
        app,
        [
            "process",
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            "--folder",
            "Inbox/Meetings/",
            "--dry-run",
            "--no-llm",
        ],
    )

    assert result.exit_code == 0
    assert "Dry run preview:" in result.output
    assert "output_path:" in result.output


def test_open_latest_uses_state_and_open_command(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    note_path = tmp_path / "vault" / "Inbox" / "Meetings" / "latest.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("note", encoding="utf-8")

    entries = [
        StateEntry(
            granola_id="g1",
            transcript_hash="h1",
            source_key="g1",
            source_url="https://notes.granola.ai/t/1",
            transcript_path="/tmp/t1.txt",
            last_processed_at="2026-03-01T10:00:00-06:00",
            output_path=str(note_path),
            status="processed",
        )
    ]
    monkeypatch.setattr("meeting_agent.cli.load_state", lambda: entries)

    calls: list[list[str]] = []

    def _mock_run(cmd: list[str], check: bool) -> None:
        assert check is True
        calls.append(cmd)

    monkeypatch.setattr("meeting_agent.cli.subprocess.run", _mock_run)

    result = runner.invoke(app, ["open", "--latest"])

    assert result.exit_code == 0
    assert calls and calls[0][0] == "open"
    assert str(note_path) in calls[0]
