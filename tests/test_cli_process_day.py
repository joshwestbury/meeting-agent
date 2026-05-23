from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from meeting_agent.cli import app
from meeting_agent.config import AppConfig
from meeting_agent.retrieval import MeetingCandidate
from meeting_agent.state import StateEntry


@pytest.fixture(autouse=True)
def _empty_cli_state(monkeypatch) -> None:
    monkeypatch.setattr("meeting_agent.cli.load_state", lambda: [])


def _config(tmp_path: Path) -> AppConfig:
    vault_root = tmp_path / "vault"
    vault_root.mkdir(exist_ok=True)
    return AppConfig(
        vault_root=vault_root,
        staging_root=tmp_path / "staging",
        default_folder="Inbox/Meetings/",
        timezone="local",
        auth_mode="token",
        auth_token_env="MEETING_AGENT_TOKEN",
        llm_mode="none",
    )


def test_process_day_processes_selected_indices(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "meeting_agent.cli._prompt_day_folder_choice_for_candidate",
        lambda *_args, **_kwargs: "Inbox/Meetings/",
    )
    monkeypatch.setattr("meeting_agent.cli._find_existing_note_by_source_url", lambda *_args, **_kwargs: None)

    discovered = [
        MeetingCandidate(
            document_id="a",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            title="Daily 1",
            started_at="2026-03-07T08:00:00-06:00",
            has_transcript=True,
            source_url="https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b04",
        ),
        MeetingCandidate(
            document_id="b",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b05",
            title="Daily 2",
            started_at="2026-03-07T09:00:00-06:00",
            has_transcript=True,
            source_url="https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b05",
        ),
        MeetingCandidate(
            document_id="c",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b06",
            title="Daily 3",
            started_at="2026-03-07T10:00:00-06:00",
            has_transcript=True,
            source_url="https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b06",
        ),
    ]
    captured_dates: list[date] = []
    monkeypatch.setattr(
        "meeting_agent.cli.list_meetings_for_day",
        lambda _config, target_date, timezone_name="local": (
            captured_dates.append(target_date),
            discovered,
        )[1],
    )

    processed_links: list[str] = []

    def _mock_run_single_process(**kwargs) -> int:
        processed_links.append(kwargs["granola_link"])
        return 0

    monkeypatch.setattr("meeting_agent.cli._run_single_process", _mock_run_single_process)

    result = runner.invoke(app, ["process-day", "--date", "2026-03-07", "--yes", "--no-llm"], input="1,3\n")

    assert result.exit_code == 0
    assert captured_dates == [date(2026, 3, 7)]
    assert processed_links == [
        "https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b04",
        "https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b06",
    ]
    assert "Day processing summary:" in result.output


def test_process_day_reprompts_after_invalid_selection(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "meeting_agent.cli._prompt_day_folder_choice_for_candidate",
        lambda *_args, **_kwargs: "Inbox/Meetings/",
    )
    monkeypatch.setattr("meeting_agent.cli._find_existing_note_by_source_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "meeting_agent.cli.list_meetings_for_day",
        lambda *_args, **_kwargs: [
            MeetingCandidate(
                document_id="a",
                meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
                title="Daily 1",
                started_at="2026-03-07T08:00:00-06:00",
                has_transcript=True,
                source_url="https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b04",
            )
        ],
    )
    calls = {"count": 0}

    def _mock_run_single_process(**kwargs) -> int:
        calls["count"] += 1
        return 0

    monkeypatch.setattr("meeting_agent.cli._run_single_process", _mock_run_single_process)

    result = runner.invoke(app, ["process-day", "--date", "2026-03-07", "--yes", "--no-llm"], input="5\nall\n")

    assert result.exit_code == 0
    assert "Invalid selection." in result.output
    assert calls["count"] == 1


def test_process_day_no_candidates_exits_cleanly(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    monkeypatch.setattr("meeting_agent.cli.list_meetings_for_day", lambda *_args, **_kwargs: [])

    result = runner.invoke(app, ["process-day", "--date", "2026-03-07"])

    assert result.exit_code == 0
    assert "No transcript-ready meetings found for 2026-03-07." in result.output


def test_default_ma_flow_accepts_global_date_flag(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    captured_dates: list[date] = []
    monkeypatch.setattr(
        "meeting_agent.cli.list_meetings_for_day",
        lambda _config, target_date, timezone_name="local": (
            captured_dates.append(target_date),
            [],
        )[1],
    )

    result = runner.invoke(app, ["--date", "2026-03-06"])

    assert result.exit_code == 0
    assert captured_dates == [date(2026, 3, 6)]
    assert "No transcript-ready meetings found for 2026-03-06." in result.output


def test_process_day_folder_prompt_falls_back_to_inbox(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "meeting_agent.cli.list_meetings_for_day",
        lambda *_args, **_kwargs: [
            MeetingCandidate(
                document_id="a",
                meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
                title="Daily 1",
                started_at="2026-03-07T08:00:00-06:00",
                has_transcript=True,
                source_url="https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b04",
            )
        ],
    )
    monkeypatch.setattr("meeting_agent.cli._resolve_folder_hint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("meeting_agent.cli._find_existing_note_by_source_url", lambda *_args, **_kwargs: None)

    captured_folders: list[str] = []

    def _mock_run_single_process(**kwargs) -> int:
        captured_folders.append(kwargs["folder_choice"])
        return 0

    monkeypatch.setattr("meeting_agent.cli._run_single_process", _mock_run_single_process)

    result = runner.invoke(
        app,
        ["process-day", "--date", "2026-03-07", "--yes", "--no-llm"],
        input="1\nUnknownFolder\n",
    )

    assert result.exit_code == 0
    assert "Falling back to: Inbox/" in result.output
    assert captured_folders == ["Inbox/"]


def test_process_day_prompts_folder_per_selected_meeting(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "meeting_agent.cli.list_meetings_for_day",
        lambda *_args, **_kwargs: [
            MeetingCandidate(
                document_id="a",
                meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
                title="One",
                started_at="2026-03-07T08:00:00-06:00",
                has_transcript=True,
                source_url="https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b04",
            ),
            MeetingCandidate(
                document_id="b",
                meeting_id="29250e01-0751-4e02-9b24-f6d06f878b05",
                title="Two",
                started_at="2026-03-07T09:00:00-06:00",
                has_transcript=True,
                source_url="https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b05",
            ),
        ],
    )
    monkeypatch.setattr("meeting_agent.cli._find_existing_note_by_source_url", lambda *_args, **_kwargs: None)
    prompted_titles: list[str] = []
    monkeypatch.setattr(
        "meeting_agent.cli._prompt_day_folder_choice_for_candidate",
        lambda _config, candidate, **_kwargs: (
            prompted_titles.append(candidate.title or ""),
            "Inbox/Meetings/",
        )[1],
    )
    monkeypatch.setattr("meeting_agent.cli._run_single_process", lambda **_kwargs: 0)

    result = runner.invoke(app, ["process-day", "--date", "2026-03-07", "--yes", "--no-llm"], input="1-2\n")

    assert result.exit_code == 0
    assert prompted_titles == ["One", "Two"]


def test_process_day_folder_prompt_shows_progress_and_reuses_previous_folder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _config(tmp_path)
    (config.vault_root / "Clients" / "Acme").mkdir(parents=True)
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: config)
    monkeypatch.setattr(
        "meeting_agent.cli.list_meetings_for_day",
        lambda *_args, **_kwargs: [
            MeetingCandidate(
                document_id="a",
                meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
                title="One",
                started_at="2026-03-07T08:00:00-06:00",
                has_transcript=True,
                source_url="https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b04",
            ),
            MeetingCandidate(
                document_id="b",
                meeting_id="29250e01-0751-4e02-9b24-f6d06f878b05",
                title="Two",
                started_at="2026-03-07T09:00:00-06:00",
                has_transcript=True,
                source_url="https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b05",
            ),
        ],
    )
    monkeypatch.setattr("meeting_agent.cli._find_existing_note_by_source_url", lambda *_args, **_kwargs: None)
    captured_folders: list[str] = []
    monkeypatch.setattr(
        "meeting_agent.cli._run_single_process",
        lambda **kwargs: (captured_folders.append(kwargs["folder_choice"]), 0)[1],
    )

    result = runner.invoke(
        app,
        ["process-day", "--date", "2026-03-07", "--yes", "--no-llm"],
        input="1-2\nClients/Acme\n\n",
    )

    assert result.exit_code == 0
    assert "Select meetings to import (`all`, `1,3`, `2-5`; Enter = none)" in result.output
    assert "Selected 2 meeting(s):" in result.output
    assert "[1/2] Which folder should One go to?" in result.output
    assert "[2/2] Which folder should Two go to?" in result.output
    assert "[Clients/Acme/]" in result.output
    assert captured_folders == ["Clients/Acme/", "Clients/Acme/"]


def test_process_day_skips_state_duplicate_before_folder_prompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _config(tmp_path)
    existing_note = config.vault_root / "Inbox" / "Existing.md"
    existing_note.parent.mkdir(parents=True)
    existing_note.write_text("---\nsource_url: https://notes.granola.ai/t/old-token\n---\n", encoding="utf-8")
    meeting_id = "29250e01-0751-4e02-9b24-f6d06f878b04"
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: config)
    monkeypatch.setattr(
        "meeting_agent.cli.list_meetings_for_day",
        lambda *_args, **_kwargs: [
            MeetingCandidate(
                document_id="a",
                meeting_id=meeting_id,
                title="Already imported",
                started_at="2026-03-07T08:00:00-06:00",
                has_transcript=True,
                source_url=f"https://notes.granola.ai/d/{meeting_id}",
            )
        ],
    )
    monkeypatch.setattr(
        "meeting_agent.cli.load_state",
        lambda: [
            StateEntry(
                granola_id=meeting_id,
                transcript_hash="hash",
                source_key=meeting_id,
                source_url="https://notes.granola.ai/t/different-token",
                transcript_path="/tmp/transcript.txt",
                last_processed_at="2026-03-07T08:30:00-06:00",
                output_path=str(existing_note),
                status="processed",
            )
        ],
    )
    monkeypatch.setattr(
        "meeting_agent.cli._prompt_day_folder_choice_for_candidate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not prompt duplicate")),
    )
    monkeypatch.setattr(
        "meeting_agent.cli._run_single_process",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not process duplicate")),
    )

    result = runner.invoke(app, ["process-day", "--date", "2026-03-07", "--yes", "--no-llm"], input="1\n")

    assert result.exit_code == 0
    assert f"Skipped duplicate source_url. Existing note: {existing_note}" in result.output
    assert "- skipped_existing_source_url: 1" in result.output


def test_process_day_skips_document_id_state_duplicate_before_folder_prompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _config(tmp_path)
    existing_note = config.vault_root / "Inbox" / "Existing.md"
    existing_note.parent.mkdir(parents=True)
    existing_note.write_text("---\nsource_url: https://notes.granola.ai/t/old-token\n---\n", encoding="utf-8")
    document_id = "324bd317-faf9-4433-9e8d-4dca73df343c"
    meeting_id = "calendar-meeting-id-that-differs-from-document-id"
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: config)
    monkeypatch.setattr(
        "meeting_agent.cli.list_meetings_for_day",
        lambda *_args, **_kwargs: [
            MeetingCandidate(
                document_id=document_id,
                meeting_id=meeting_id,
                title="Already imported",
                started_at="2026-03-07T08:00:00-06:00",
                has_transcript=True,
                source_url=f"https://notes.granola.ai/d/{meeting_id}",
            )
        ],
    )
    monkeypatch.setattr(
        "meeting_agent.cli.load_state",
        lambda: [
            StateEntry(
                granola_id=document_id,
                transcript_hash="hash",
                source_key=document_id,
                source_url="https://notes.granola.ai/t/different-token",
                transcript_path=f"/tmp/{document_id}.txt",
                last_processed_at="2026-03-07T08:30:00-06:00",
                output_path=str(existing_note),
                status="processed",
            )
        ],
    )
    monkeypatch.setattr(
        "meeting_agent.cli._prompt_day_folder_choice_for_candidate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not prompt duplicate")),
    )
    monkeypatch.setattr(
        "meeting_agent.cli._run_single_process",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not process duplicate")),
    )

    result = runner.invoke(app, ["process-day", "--date", "2026-03-07", "--yes", "--no-llm"], input="1\n")

    assert result.exit_code == 0
    assert f"Skipped duplicate source_url. Existing note: {existing_note}" in result.output
    assert "- skipped_existing_source_url: 1" in result.output
