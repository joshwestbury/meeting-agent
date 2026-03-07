from pathlib import Path

import yaml
from typer.testing import CliRunner

from meeting_agent.cli import app
from meeting_agent.config import AppConfig
from meeting_agent.errors import CollisionError, SchemaValidationError
from meeting_agent.pipeline import PipelineResult
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


def test_process_new_continues_after_item_failure(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    monkeypatch.setattr("meeting_agent.cli.load_state", lambda: [])
    transcripts = tmp_path / "staging" / "transcripts"
    transcripts.mkdir(parents=True, exist_ok=True)
    (transcripts / "a.txt").write_text("one", encoding="utf-8")
    (transcripts / "b.txt").write_text("two", encoding="utf-8")

    def _mock_process_note_write(**kwargs):
        if kwargs["meeting_id"] == "a":
            raise CollisionError("boom")
        return PipelineResult(
            status="processed",
            output_path=tmp_path / "vault" / "Inbox" / "Meetings" / "b.md",
            quarantine_path=None,
            decision_reason="no_matching_identity",
        )

    monkeypatch.setattr("meeting_agent.cli.process_note_write", _mock_process_note_write)

    result = runner.invoke(app, ["process", "--new", "--folder", "Inbox/Meetings/", "--yes", "--no-llm"])

    assert result.exit_code == 1
    assert "Batch summary:" in result.output
    assert "- processed: 1" in result.output
    assert "- failed: 1" in result.output


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


def test_process_default_writes_full_transcript_section(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))

    def _mock_retrieve(_: str, __: AppConfig, client=None, max_retries: int = 2) -> RetrievalResult:
        return RetrievalResult(
            granola_id="g1",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            title="Weekly Sync",
            started_at="2026-03-01T09:12:00-06:00",
            attendees=[],
            transcript_text="Speaker A: hello\nSpeaker B: hi",
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
            "--yes",
            "--no-llm",
        ],
    )
    assert result.exit_code == 0
    note_files = list((tmp_path / "vault" / "Inbox" / "Meetings").glob("*.md"))
    assert len(note_files) == 1
    content = note_files[0].read_text(encoding="utf-8")
    assert "## Full Transcript" in content
    assert "Speaker A: hello" in content


def test_process_summary_mode_omits_full_transcript_section(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))

    def _mock_retrieve(_: str, __: AppConfig, client=None, max_retries: int = 2) -> RetrievalResult:
        return RetrievalResult(
            granola_id="g1",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            title="Weekly Sync",
            started_at="2026-03-01T09:12:00-06:00",
            attendees=[],
            transcript_text="Speaker A: hello\nSpeaker B: hi",
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
            "--yes",
            "--no-llm",
            "--summary",
        ],
    )
    assert result.exit_code == 0
    note_files = list((tmp_path / "vault" / "Inbox" / "Meetings").glob("*.md"))
    assert len(note_files) == 1
    content = note_files[0].read_text(encoding="utf-8")
    assert "## Full Transcript" not in content


def test_process_folder_hint_resolves_case_insensitive(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))
    (tmp_path / "vault" / "Alter Mentis" / "Inbox").mkdir(parents=True, exist_ok=True)

    def _mock_retrieve(_: str, __: AppConfig, client=None, max_retries: int = 2) -> RetrievalResult:
        return RetrievalResult(
            granola_id="g1",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            title="Weekly Sync",
            started_at="2026-03-01T09:12:00-06:00",
            attendees=[],
            transcript_text="Speaker A: hello",
            raw_payload={},
        )

    monkeypatch.setattr("meeting_agent.cli.retrieve_transcript", _mock_retrieve)
    result = runner.invoke(
        app,
        [
            "process",
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            "--folder",
            "alter mentis/inbox",
            "--yes",
            "--no-llm",
        ],
    )
    assert result.exit_code == 0
    assert "Folder resolved: alter mentis/inbox -> Alter Mentis/Inbox/" in result.output
    note_files = list((tmp_path / "vault" / "Alter Mentis" / "Inbox").glob("*.md"))
    assert len(note_files) == 1


def test_process_folder_hint_falls_back_to_default_when_no_match(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))

    def _mock_retrieve(_: str, __: AppConfig, client=None, max_retries: int = 2) -> RetrievalResult:
        return RetrievalResult(
            granola_id="g1",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            title="Weekly Sync",
            started_at="2026-03-01T09:12:00-06:00",
            attendees=[],
            transcript_text="Speaker A: hello",
            raw_payload={},
        )

    monkeypatch.setattr("meeting_agent.cli.retrieve_transcript", _mock_retrieve)
    result = runner.invoke(
        app,
        [
            "process",
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            "--folder",
            "totally missing folder",
            "--yes",
            "--no-llm",
        ],
    )
    assert result.exit_code == 0
    assert "Falling back to default: Inbox/Meetings/" in result.output
    note_files = list((tmp_path / "vault" / "Inbox" / "Meetings").glob("*.md"))
    assert len(note_files) == 1


def test_process_folder_hint_uses_default_root_prefix(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    config = _config(tmp_path)
    config.default_folder = "Alter Mentis/Inbox/"
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: config)
    (tmp_path / "vault" / "Alter Mentis" / "Drata").mkdir(parents=True, exist_ok=True)

    def _mock_retrieve(_: str, __: AppConfig, client=None, max_retries: int = 2) -> RetrievalResult:
        return RetrievalResult(
            granola_id="g1",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            title="Weekly Sync",
            started_at="2026-03-01T09:12:00-06:00",
            attendees=[],
            transcript_text="Speaker A: hello",
            raw_payload={},
        )

    monkeypatch.setattr("meeting_agent.cli.retrieve_transcript", _mock_retrieve)
    result = runner.invoke(
        app,
        [
            "process",
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            "--folder",
            "Drata",
            "--yes",
            "--no-llm",
        ],
    )
    assert result.exit_code == 0
    assert "Folder resolved: Drata -> Alter Mentis/Drata/" in result.output
    note_files = list((tmp_path / "vault" / "Alter Mentis" / "Drata").glob("*.md"))
    assert len(note_files) == 1


def test_process_local_mode_invokes_server_ensure(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    config = _config(tmp_path)
    config.llm_mode = "local"
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: config)

    def _mock_retrieve(_: str, __: AppConfig, client=None, max_retries: int = 2) -> RetrievalResult:
        return RetrievalResult(
            granola_id="g1",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            title="Weekly Sync",
            started_at="2026-03-01T09:12:00-06:00",
            attendees=[],
            transcript_text="Speaker A: hello",
            raw_payload={},
        )

    monkeypatch.setattr("meeting_agent.cli.retrieve_transcript", _mock_retrieve)
    called = {"ensure": False}

    def _mock_ensure(_: AppConfig) -> None:
        called["ensure"] = True

    monkeypatch.setattr("meeting_agent.cli._ensure_local_llm_server", _mock_ensure)

    from meeting_agent.note_schema import NotePayload

    monkeypatch.setattr(
        "meeting_agent.cli.generate_note_payload_with_local_runtime",
        lambda *_args, **_kwargs: NotePayload.model_validate(
            {
                "title": "LLM Title",
                "meeting_date": "2026-03-01",
                "attendees": [],
                "client": "",
                "project": "",
                "tags": ["meeting"],
                "folder_choice": "Inbox/Meetings/",
                "summary": "Summary",
                "action_items": [],
                "key_details": ["detail"],
                "sensitive": False,
            }
        ),
    )

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
    assert called["ensure"] is True
    note_files = list((tmp_path / "vault" / "Inbox" / "Meetings").glob("*.md"))
    assert len(note_files) == 1
    assert "Weekly Sync - 2026-03-01.md" == note_files[0].name
    parts = note_files[0].read_text(encoding="utf-8").split("---\n")
    frontmatter = yaml.safe_load(parts[1])
    assert frontmatter["tags"] == [
        "meeting",
        "granola-meeting-agent",
        "meeting-transcript",
        "meetings",
    ]


def test_process_no_llm_does_not_invoke_server_ensure(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    config = _config(tmp_path)
    config.llm_mode = "local"
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: config)

    def _mock_retrieve(_: str, __: AppConfig, client=None, max_retries: int = 2) -> RetrievalResult:
        return RetrievalResult(
            granola_id="g1",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            title="Weekly Sync",
            started_at="2026-03-01T09:12:00-06:00",
            attendees=[],
            transcript_text="Speaker A: hello",
            raw_payload={},
        )

    monkeypatch.setattr("meeting_agent.cli.retrieve_transcript", _mock_retrieve)

    def _fail_ensure(_: AppConfig) -> None:
        raise AssertionError("should not be called in --no-llm mode")

    monkeypatch.setattr("meeting_agent.cli._ensure_local_llm_server", _fail_ensure)

    result = runner.invoke(
        app,
        [
            "process",
            "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
            "--folder",
            "Inbox/Meetings/",
            "--yes",
            "--no-llm",
        ],
    )
    assert result.exit_code == 0


def test_process_llm_schema_failure_falls_back_to_no_llm(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    config = _config(tmp_path)
    config.llm_mode = "local"
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: config)

    def _mock_retrieve(_: str, __: AppConfig, client=None, max_retries: int = 2) -> RetrievalResult:
        return RetrievalResult(
            granola_id="g1",
            meeting_id="29250e01-0751-4e02-9b24-f6d06f878b04",
            title="Weekly Sync",
            started_at="2026-03-01T09:12:00-06:00",
            attendees=[],
            transcript_text="Speaker A: hello",
            raw_payload={},
        )

    monkeypatch.setattr("meeting_agent.cli.retrieve_transcript", _mock_retrieve)
    monkeypatch.setattr("meeting_agent.cli._ensure_local_llm_server", lambda _config: None)
    monkeypatch.setattr(
        "meeting_agent.cli.generate_note_payload_with_local_runtime",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SchemaValidationError("meeting_date must be YYYY-MM-DD")
        ),
    )

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
    assert "falling back to deterministic template" in result.output
    note_files = list((tmp_path / "vault" / "Inbox" / "Meetings").glob("*.md"))
    assert len(note_files) == 1


def test_process_new_updates_when_staged_hash_changes(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("meeting_agent.cli.load_and_validate_startup_config", lambda: _config(tmp_path))

    transcripts = tmp_path / "staging" / "transcripts"
    transcripts.mkdir(parents=True, exist_ok=True)
    target = transcripts / "a.txt"
    target.write_text("version one", encoding="utf-8")

    first = runner.invoke(app, ["process", "--new", "--folder", "Inbox/Meetings/", "--yes", "--no-llm"])
    assert first.exit_code == 0
    assert "- processed: 1" in first.output

    target.write_text("version two", encoding="utf-8")
    second = runner.invoke(app, ["process", "--new", "--folder", "Inbox/Meetings/", "--yes", "--no-llm"])
    assert second.exit_code == 0
    assert "- updated: 1" in second.output


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
