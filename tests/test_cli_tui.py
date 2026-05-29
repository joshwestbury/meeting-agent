from datetime import date
import asyncio
from pathlib import Path

from typer.testing import CliRunner

from meeting_agent.cli import app
from meeting_agent.cli import _shorten_tui_path
from meeting_agent.config import AppConfig
from meeting_agent.errors import RetrievalError
from meeting_agent.retrieval import MeetingCandidate
from textual.widgets import Input


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


def test_tui_command_uses_requested_date(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))

    captured_dates: list[date] = []

    def _mock_run_tui(_config: AppConfig, *, target_date: date, **_kwargs) -> None:
        captured_dates.append(target_date)

    import meeting_agent.tui

    monkeypatch.setattr(meeting_agent.tui, "run_tui", _mock_run_tui)

    result = runner.invoke(app, ["tui", "--date", "2026-03-07"])

    assert result.exit_code == 0
    assert captured_dates == [date(2026, 3, 7)]


def test_default_command_opens_tui_for_today(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))

    captured_dates: list[date] = []

    def _mock_run_tui(_config: AppConfig, *, target_date: date, **_kwargs) -> None:
        captured_dates.append(target_date)

    import meeting_agent.tui

    monkeypatch.setattr(meeting_agent.tui, "run_tui", _mock_run_tui)

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert captured_dates == [date.today()]


def test_default_command_processes_tui_selection(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    monkeypatch.setattr("meeting_agent.cli._find_existing_note_for_candidate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("meeting_agent.cli._session_ensure_local_llm_if_needed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "meeting_agent.cli._prompt_day_folder_choice_for_candidate",
        lambda *_args, **_kwargs: "Inbox/Meetings/",
    )

    selected = MeetingCandidate(
        document_id="doc-1",
        meeting_id="meeting-1",
        title="Design Review",
        started_at="2026-03-07T08:00:00-06:00",
        has_transcript=True,
        source_url="https://notes.granola.ai/d/meeting-1",
    )

    import meeting_agent.tui

    processed_links: list[str] = []
    emitted: list[str] = []

    def _mock_run_single_process(**kwargs) -> int:
        processed_links.append(kwargs["granola_link"])
        assert kwargs["folder_choice"] == "Inbox/Meetings/"
        assert kwargs["confirm_write"] is False
        assert kwargs["command_name"] == "tui"
        kwargs["emit"](f"Note written: {tmp_path / 'vault' / 'Inbox' / 'Meetings' / 'note.md'}")
        return 0

    def _mock_run_tui(*_args, **kwargs) -> None:
        kwargs["process_meeting"](selected, emitted.append)

    monkeypatch.setattr(meeting_agent.tui, "run_tui", _mock_run_tui)
    monkeypatch.setattr("meeting_agent.cli._run_single_process", _mock_run_single_process)

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert processed_links == ["https://notes.granola.ai/d/meeting-1"]
    assert "Note written: Inbox/Meetings/note.md" in emitted


def test_default_command_resolves_tui_folder_input_to_existing_projects_folder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _config(tmp_path)
    (config.vault_root / "Projects" / "Quickbase").mkdir(parents=True)
    (config.vault_root / "Products" / "Quickbase").mkdir(parents=True)
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: config)

    selected = MeetingCandidate(
        document_id="doc-1",
        meeting_id="meeting-1",
        title="Quickbase Review",
        started_at="2026-05-27T12:00:00-05:00",
        has_transcript=True,
        source_url="https://notes.granola.ai/d/meeting-1",
    )

    import meeting_agent.tui

    captured_folders: list[str] = []
    emitted: list[str] = []

    def _mock_run_single_process(**kwargs) -> int:
        captured_folders.append(kwargs["folder_choice"])
        return 0

    def _mock_run_tui(*_args, **kwargs) -> None:
        kwargs["process_meeting"](selected, emitted.append, "quickbase")

    monkeypatch.setattr(meeting_agent.tui, "run_tui", _mock_run_tui)
    monkeypatch.setattr("meeting_agent.cli._run_single_process", _mock_run_single_process)

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert captured_folders == ["Projects/Quickbase/"]
    assert "Folder resolved: quickbase -> Projects/Quickbase/" in emitted


def test_default_command_duplicate_output_is_multiline_and_relative(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    config = _config(tmp_path)
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: config)
    existing_note = config.vault_root / "Inbox" / "Design Review.md"
    selected = MeetingCandidate(
        document_id="doc-1",
        meeting_id="meeting-1",
        title="Design Review",
        started_at="2026-03-07T08:00:00-06:00",
        has_transcript=True,
        source_url="https://notes.granola.ai/d/meeting-1",
    )
    monkeypatch.setattr("meeting_agent.cli._build_existing_note_lookup", lambda _config: lambda _candidate: existing_note)

    import meeting_agent.tui

    emitted: list[str] = []

    def _mock_run_tui(*_args, **kwargs) -> None:
        kwargs["process_meeting"](selected, emitted.append)

    monkeypatch.setattr(meeting_agent.tui, "run_tui", _mock_run_tui)

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert emitted == ["Skipped duplicate source_url.", "Existing note: Inbox/Design Review.md"]


def test_tui_command_rejects_invalid_date(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("MEETING_AGENT_TOKEN", "secret")
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))

    result = runner.invoke(app, ["tui", "--date", "bad-date"])

    assert result.exit_code == 3
    assert "Invalid --date format. Expected YYYY-MM-DD." in result.output


def test_tui_loads_meetings_in_headless_mode(tmp_path: Path, monkeypatch) -> None:
    import meeting_agent.tui

    monkeypatch.setattr(
        "meeting_agent.tui.list_meetings_for_day",
        lambda *_args, **_kwargs: [
            MeetingCandidate(
                document_id="doc-1",
                meeting_id="meeting-1",
                title="Design Review",
                started_at="2026-03-07T08:00:00-06:00",
                has_transcript=True,
                source_url="https://notes.granola.ai/d/meeting-1",
            )
        ],
    )

    async def _run() -> None:
        tui_app = meeting_agent.tui.create_tui_app(_config(tmp_path), target_date=date(2026, 3, 7))
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            assert len(tui_app.candidates) == 1
            assert tui_app.selected_index == 0

    asyncio.run(_run())


def test_tui_discovery_auth_error_is_reported_in_output(tmp_path: Path, monkeypatch) -> None:
    import meeting_agent.tui

    def _raise_auth_error(*_args, **_kwargs):
        raise RetrievalError("auth_required", "Desktop-session token refresh rejected: test details")

    monkeypatch.setattr("meeting_agent.tui.list_meetings_for_day", _raise_auth_error)

    async def _run() -> None:
        tui_app = meeting_agent.tui.create_tui_app(_config(tmp_path), target_date=date(2026, 3, 7))
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            assert "Discovery failed." in str(tui_app.query_one("#status").render())
            assert any("Meeting discovery failed" in line for line in tui_app.output_lines)
            assert "Try: meeting-agent auth-import" in tui_app.output_lines

    asyncio.run(_run())


def test_tui_uses_arrow_keys_to_select_meetings(tmp_path: Path, monkeypatch) -> None:
    import meeting_agent.tui

    monkeypatch.setattr(
        "meeting_agent.tui.list_meetings_for_day",
        lambda *_args, **_kwargs: [
            MeetingCandidate(
                document_id="doc-1",
                meeting_id="meeting-1",
                title="Design Review",
                started_at="2026-03-07T08:00:00-06:00",
                has_transcript=True,
                source_url="https://notes.granola.ai/d/meeting-1",
            ),
            MeetingCandidate(
                document_id="doc-2",
                meeting_id="meeting-2",
                title="Client Followup",
                started_at="2026-03-07T09:00:00-06:00",
                has_transcript=True,
                source_url="https://notes.granola.ai/d/meeting-2",
            ),
        ],
    )

    async def _run() -> None:
        tui_app = meeting_agent.tui.create_tui_app(_config(tmp_path), target_date=date(2026, 3, 7))
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            assert tui_app.selected_index == 1

    asyncio.run(_run())


def test_tui_enter_returns_selected_meeting(tmp_path: Path, monkeypatch) -> None:
    import meeting_agent.tui

    selected = MeetingCandidate(
        document_id="doc-1",
        meeting_id="meeting-1",
        title="Design Review",
        started_at="2026-03-07T08:00:00-06:00",
        has_transcript=True,
        source_url="https://notes.granola.ai/d/meeting-1",
    )
    monkeypatch.setattr("meeting_agent.tui.list_meetings_for_day", lambda *_args, **_kwargs: [selected])

    async def _run() -> None:
        tui_app = meeting_agent.tui.create_tui_app(_config(tmp_path), target_date=date(2026, 3, 7))
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
        assert tui_app.return_value == selected

    asyncio.run(_run())


def test_tui_enter_runs_processing_callback_without_exiting(tmp_path: Path, monkeypatch) -> None:
    import meeting_agent.tui

    selected = MeetingCandidate(
        document_id="doc-1",
        meeting_id="meeting-1",
        title="Design Review",
        started_at="2026-03-07T08:00:00-06:00",
        has_transcript=True,
        source_url="https://notes.granola.ai/d/meeting-1",
    )
    monkeypatch.setattr("meeting_agent.tui.list_meetings_for_day", lambda *_args, **_kwargs: [selected])
    processed: list[str] = []

    def _process(candidate: MeetingCandidate, emit, _folder_choice=None) -> None:
        processed.append(candidate.source_url)
        emit("done")

    async def _run() -> None:
        tui_app = meeting_agent.tui.create_tui_app(
            _config(tmp_path),
            target_date=date(2026, 3, 7),
            process_meeting=_process,
        )
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            folder_input = tui_app.query_one("#folder-input", Input)
            assert folder_input.has_class("visible")
            folder_input.value = "Projects/A"
            await pilot.press("enter")
            await pilot.pause()
            assert processed == ["https://notes.granola.ai/d/meeting-1"]
            assert tui_app.return_value is None
            assert "done" in tui_app.output_lines
            assert "Done." in tui_app.output_lines

    asyncio.run(_run())


def test_tui_path_shortening_keeps_project_and_folder_context() -> None:
    path = "Projects/Quickbase/SCG QB FF - Lead conversions with technical implementation review - 2026-05-27.md"

    shortened = _shorten_tui_path(path, max_length=68)

    assert shortened.startswith("Projects/Quickbase/")
    assert shortened.endswith("…")
    assert len(shortened) <= 68


def test_tui_single_meeting_prompts_for_folder_before_processing(tmp_path: Path, monkeypatch) -> None:
    import meeting_agent.tui

    selected = MeetingCandidate(
        document_id="doc-1",
        meeting_id="meeting-1",
        title="Design Review",
        started_at="2026-03-07T08:00:00-06:00",
        has_transcript=True,
        source_url="https://notes.granola.ai/d/meeting-1",
    )
    monkeypatch.setattr("meeting_agent.tui.list_meetings_for_day", lambda *_args, **_kwargs: [selected])
    processed: list[tuple[str, str | None]] = []

    def _process(candidate: MeetingCandidate, emit, folder_choice=None) -> None:
        processed.append((candidate.source_url, folder_choice))
        emit("done")

    async def _run() -> None:
        tui_app = meeting_agent.tui.create_tui_app(
            _config(tmp_path),
            target_date=date(2026, 3, 7),
            process_meeting=_process,
        )
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert processed == []
            folder_input = tui_app.query_one("#folder-input", Input)
            assert "Destination Folder" in str(tui_app.query_one("#output-row").border_title)
            assert tui_app.query_one("#folder-label").has_class("visible")
            assert "type folder name" in str(tui_app.query_one("#status").render())
            assert folder_input.has_class("visible")
            folder_input.value = "Projects/A"
            await pilot.press("enter")
            await pilot.pause()
            assert processed == [("https://notes.granola.ai/d/meeting-1", "Projects/A")]
            assert "Retrieving transcript..." in tui_app.output_lines

    asyncio.run(_run())


def test_tui_enter_on_duplicate_reports_existing_note_without_processing(tmp_path: Path, monkeypatch) -> None:
    import meeting_agent.tui

    selected = MeetingCandidate(
        document_id="doc-1",
        meeting_id="meeting-1",
        title="Design Review",
        started_at="2026-03-07T08:00:00-06:00",
        has_transcript=True,
        source_url="https://notes.granola.ai/d/meeting-1",
    )
    existing_note = tmp_path / "vault" / "Inbox" / "Design Review.md"
    monkeypatch.setattr("meeting_agent.tui.list_meetings_for_day", lambda *_args, **_kwargs: [selected])
    processed: list[str] = []

    def _process(candidate: MeetingCandidate, emit, _folder_choice=None) -> None:
        processed.append(candidate.source_url)
        emit("processed")

    async def _run() -> None:
        tui_app = meeting_agent.tui.create_tui_app(
            _config(tmp_path),
            target_date=date(2026, 3, 7),
            process_meeting=_process,
            existing_note_for_candidate=lambda _candidate: existing_note,
        )
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            assert "[imported]" in tui_app._candidate_label(selected)
            await pilot.press("enter")
            await pilot.pause()
            assert processed == []
            assert any("Skipped duplicate source_url" in line for line in tui_app.output_lines)
            assert "Existing note: Inbox/Design Review.md" in tui_app.output_lines

    asyncio.run(_run())


def test_tui_import_all_prompts_for_each_unimported_meeting(tmp_path: Path, monkeypatch) -> None:
    import meeting_agent.tui

    first = MeetingCandidate(
        document_id="doc-1",
        meeting_id="meeting-1",
        title="Design Review",
        started_at="2026-03-07T08:00:00-06:00",
        has_transcript=True,
        source_url="https://notes.granola.ai/d/meeting-1",
    )
    second = MeetingCandidate(
        document_id="doc-2",
        meeting_id="meeting-2",
        title="Client Followup",
        started_at="2026-03-07T09:00:00-06:00",
        has_transcript=True,
        source_url="https://notes.granola.ai/d/meeting-2",
    )
    monkeypatch.setattr("meeting_agent.tui.list_meetings_for_day", lambda *_args, **_kwargs: [first, second])
    processed: list[tuple[str, str | None]] = []

    def _process(candidate: MeetingCandidate, emit, folder_choice=None) -> None:
        processed.append((candidate.source_url, folder_choice))
        emit(f"processed {candidate.meeting_id}")

    async def _run() -> None:
        tui_app = meeting_agent.tui.create_tui_app(
            _config(tmp_path),
            target_date=date(2026, 3, 7),
            process_meeting=_process,
        )
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down", "down", "enter")
            await pilot.pause()
            folder_input = tui_app.query_one("#folder-input", Input)
            assert folder_input.has_class("visible")

            folder_input.value = "Projects/A"
            await pilot.press("enter")
            await pilot.pause()
            assert processed == [("https://notes.granola.ai/d/meeting-1", "Projects/A")]

            folder_input.value = "Projects/B"
            await pilot.press("enter")
            await pilot.pause()
            assert processed == [
                ("https://notes.granola.ai/d/meeting-1", "Projects/A"),
                ("https://notes.granola.ai/d/meeting-2", "Projects/B"),
            ]
            for _ in range(10):
                if "Import all complete." in tui_app.output_lines:
                    break
                await pilot.pause()
            assert "Import all complete." in tui_app.output_lines

    asyncio.run(_run())


def test_tui_import_all_skips_imported_meetings(tmp_path: Path, monkeypatch) -> None:
    import meeting_agent.tui

    first = MeetingCandidate(
        document_id="doc-1",
        meeting_id="meeting-1",
        title="Design Review",
        started_at="2026-03-07T08:00:00-06:00",
        has_transcript=True,
        source_url="https://notes.granola.ai/d/meeting-1",
    )
    second = MeetingCandidate(
        document_id="doc-2",
        meeting_id="meeting-2",
        title="Client Followup",
        started_at="2026-03-07T09:00:00-06:00",
        has_transcript=True,
        source_url="https://notes.granola.ai/d/meeting-2",
    )
    existing_note = tmp_path / "vault" / "Inbox" / "Design Review.md"
    monkeypatch.setattr("meeting_agent.tui.list_meetings_for_day", lambda *_args, **_kwargs: [first, second])
    processed: list[str] = []

    def _process(candidate: MeetingCandidate, emit, folder_choice=None) -> None:
        processed.append(candidate.source_url)
        emit(f"processed {folder_choice}")

    async def _run() -> None:
        tui_app = meeting_agent.tui.create_tui_app(
            _config(tmp_path),
            target_date=date(2026, 3, 7),
            process_meeting=_process,
            existing_note_for_candidate=lambda candidate: existing_note if candidate is first else None,
        )
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            assert "Import all unimported meetings (1)" == tui_app._import_all_label()[2:]
            await pilot.press("down", "down", "enter")
            await pilot.pause()
            folder_input = tui_app.query_one("#folder-input", Input)
            folder_input.value = "Projects/B"
            await pilot.press("enter")
            await pilot.pause()
            assert processed == ["https://notes.granola.ai/d/meeting-2"]

    asyncio.run(_run())


def test_run_tui_uses_inline_terminal_mode(tmp_path: Path, monkeypatch) -> None:
    import meeting_agent.tui

    captured_kwargs: dict[str, object] = {}

    class _FakeApp:
        def run(self, **kwargs) -> None:
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(meeting_agent.tui, "create_tui_app", lambda *_args, **_kwargs: _FakeApp())

    meeting_agent.tui.run_tui(_config(tmp_path), target_date=date(2026, 3, 7))

    assert captured_kwargs["inline"] is True
    assert captured_kwargs["inline_no_clear"] is False
    assert captured_kwargs["size"] == (96, 15)
