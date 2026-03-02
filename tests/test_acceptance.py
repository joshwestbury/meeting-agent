from pathlib import Path

from typer.testing import CliRunner

from meeting_agent.cli import app
from meeting_agent.config import AppConfig
from meeting_agent.retrieval import RetrievalResult


def _config(tmp_path: Path, *, llm_mode: str = "none") -> AppConfig:
    vault_root = tmp_path / "vault"
    vault_root.mkdir(exist_ok=True)
    return AppConfig(
        vault_root=vault_root,
        staging_root=tmp_path / "staging",
        default_folder="Inbox/Meetings/",
        timezone="local",
        auth_mode="manual_export",
        llm_mode=llm_mode,  # type: ignore[arg-type]
    )


def _retrieval_result() -> RetrievalResult:
    return RetrievalResult(
        granola_id="",
        meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
        title="Weekly Sync",
        started_at="2026-03-01T09:12:00-06:00",
        attendees=[],
        transcript_text="Updates and timeline.",
        raw_payload={},
    )


def test_acceptance_interactive_prompts_and_writes_note(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    monkeypatch.setattr("meeting_agent.cli.retrieve_transcript", lambda *_args, **_kwargs: _retrieval_result())

    result = runner.invoke(
        app,
        [],
        input=(
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04\n"
            "Inbox/Meetings/\n"
            "y\n"
        ),
    )

    assert result.exit_code == 0
    notes = list((tmp_path / "vault" / "Inbox" / "Meetings").glob("*.md"))
    assert len(notes) == 1
    assert notes[0].resolve().is_relative_to((tmp_path / "vault").resolve())


def test_acceptance_same_transcript_rerun_does_not_duplicate(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    monkeypatch.setattr("meeting_agent.cli.retrieve_transcript", lambda *_args, **_kwargs: _retrieval_result())

    args = [
        "process",
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        "--folder",
        "Inbox/Meetings/",
        "--yes",
        "--no-llm",
    ]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)
    assert first.exit_code == 0
    assert second.exit_code == 0

    notes = list((tmp_path / "vault" / "Inbox" / "Meetings").glob("*.md"))
    assert len(notes) == 1


def test_acceptance_local_mode_uses_llm_path(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path, llm_mode="local"))
    monkeypatch.setattr("meeting_agent.cli.retrieve_transcript", lambda *_args, **_kwargs: _retrieval_result())
    monkeypatch.setattr("meeting_agent.cli._ensure_local_llm_server", lambda _config: None)
    called = {"llm": False}

    def _mock_llm(*_args, **_kwargs):
        called["llm"] = True
        from meeting_agent.note_schema import NotePayload

        return NotePayload.model_validate(
            {
                "title": "LLM Title",
                "meeting_date": "2030-01-01",
                "attendees": [],
                "client": "",
                "project": "",
                "tags": ["meeting"],
                "folder_choice": "Inbox/Meetings/",
                "summary": "LLM summary",
                "action_items": [],
                "key_details": ["detail"],
                "sensitive": False,
            }
        )

    monkeypatch.setattr("meeting_agent.cli.generate_note_payload_with_local_runtime", _mock_llm)

    result = runner.invoke(
        app,
        [
            "process",
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            "--folder",
            "Inbox/Meetings/",
            "--yes",
        ],
    )
    assert result.exit_code == 0
    assert called["llm"] is True
    notes = list((tmp_path / "vault" / "Inbox" / "Meetings").glob("*.md"))
    assert len(notes) == 1
    content = notes[0].read_text(encoding="utf-8")
    assert "meeting_date: '2026-03-01'" in content
    assert "2030-01-01" not in notes[0].name
