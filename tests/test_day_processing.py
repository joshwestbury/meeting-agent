from datetime import date
from pathlib import Path

from meeting_agent.config import AppConfig
from meeting_agent.day_processing import parse_candidate_selection, run_process_day
from meeting_agent.retrieval import MeetingCandidate


def _config(tmp_path: Path) -> AppConfig:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    return AppConfig(
        vault_root=vault_root,
        staging_root=tmp_path / "staging",
        auth_mode="manual_export",
        llm_mode="none",
    )


def _candidate(meeting_id: str, title: str) -> MeetingCandidate:
    return MeetingCandidate(
        document_id=meeting_id,
        meeting_id=meeting_id,
        title=title,
        started_at="2026-03-07T08:00:00-06:00",
        has_transcript=True,
        source_url=f"https://notes.granola.ai/d/{meeting_id}",
    )


def test_parse_candidate_selection_supports_ranges_and_dedupes() -> None:
    assert parse_candidate_selection("1, 2-3,2", 4) == [0, 1, 2]
    assert parse_candidate_selection("all", 3) == [0, 1, 2]
    assert parse_candidate_selection("", 3) == []
    assert parse_candidate_selection("2-1", 3) is None
    assert parse_candidate_selection("4", 3) is None


def test_run_process_day_processes_selected_candidates(tmp_path: Path) -> None:
    config = _config(tmp_path)
    emitted: list[str] = []
    processed_links: list[str] = []
    candidates = [
        _candidate("29250e01-0751-4e02-9b24-f6d06f878b04", "One"),
        _candidate("29250e01-0751-4e02-9b24-f6d06f878b05", "Two"),
    ]

    def _run_single_process(**kwargs) -> int:
        processed_links.append(kwargs["granola_link"])
        return 0

    exit_code = run_process_day(
        config=config,
        target_date=date(2026, 3, 7),
        yes=True,
        dry_run=False,
        no_llm=True,
        output_mode="full",
        emit=emitted.append,
        ensure_local_llm_if_needed=lambda _config: None,
        render_meeting_candidates=lambda _candidates, _target_date: None,
        prompt_candidate_indices=lambda _total: [1],
        prompt_folder_choice_for_candidate=lambda _config, _candidate, _position, _total, _previous: "Inbox/",
        find_existing_note_by_source_url=lambda _vault_root, _source_url: None,
        run_single_process=_run_single_process,
        discover_meetings=lambda _config, _target_date, _timezone_name: candidates,
    )

    assert exit_code == 0
    assert processed_links == ["https://notes.granola.ai/d/29250e01-0751-4e02-9b24-f6d06f878b05"]
    assert emitted == [
        "Selected 1 meeting(s):",
        "- [1/1] 2026-03-07T08:00:00-06:00 | Two",
        "Day processing summary:",
        "- selected: 1",
        "- processed: 1",
        "- skipped_existing_source_url: 0",
        "- failed: 0",
    ]


def test_run_process_day_passes_progress_and_previous_folder(tmp_path: Path) -> None:
    config = _config(tmp_path)
    prompted: list[tuple[str, int, int, str | None]] = []
    candidates = [
        _candidate("29250e01-0751-4e02-9b24-f6d06f878b04", "One"),
        _candidate("29250e01-0751-4e02-9b24-f6d06f878b05", "Two"),
    ]

    def _prompt_folder(
        _config: AppConfig,
        candidate: MeetingCandidate,
        position: int,
        total: int,
        previous_folder: str | None,
    ) -> str:
        prompted.append((candidate.title or "", position, total, previous_folder))
        return "Clients/Acme/" if position == 1 else "Clients/Acme/"

    exit_code = run_process_day(
        config=config,
        target_date=date(2026, 3, 7),
        yes=True,
        dry_run=False,
        no_llm=True,
        output_mode="full",
        emit=lambda _message: None,
        ensure_local_llm_if_needed=lambda _config: None,
        render_meeting_candidates=lambda _candidates, _target_date: None,
        prompt_candidate_indices=lambda _total: [0, 1],
        prompt_folder_choice_for_candidate=_prompt_folder,
        find_existing_note_by_source_url=lambda _vault_root, _source_url: None,
        run_single_process=lambda **_kwargs: 0,
        discover_meetings=lambda _config, _target_date, _timezone_name: candidates,
    )

    assert exit_code == 0
    assert prompted == [
        ("One", 1, 2, None),
        ("Two", 2, 2, "Clients/Acme/"),
    ]
