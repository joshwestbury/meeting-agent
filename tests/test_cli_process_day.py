from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from meeting_agent.cli import app
from meeting_agent.config import AppConfig
from meeting_agent.retrieval import MeetingCandidate


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
        lambda _config, candidate, no_llm=False: (
            prompted_titles.append(candidate.title or ""),
            "Inbox/Meetings/",
        )[1],
    )
    monkeypatch.setattr("meeting_agent.cli._run_single_process", lambda **_kwargs: 0)

    result = runner.invoke(app, ["process-day", "--date", "2026-03-07", "--yes", "--no-llm"], input="1-2\n")

    assert result.exit_code == 0
    assert prompted_titles == ["One", "Two"]
