from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from meeting_agent.config import AppConfig
from meeting_agent.errors import RetrievalError
from meeting_agent.exit_codes import exit_code_for_error, render_error_message
from meeting_agent.logging import log_event
from meeting_agent.retrieval import MeetingCandidate, list_meetings_for_day


@dataclass(frozen=True)
class DayProcessingSummary:
    selected: int = 0
    processed: int = 0
    skipped_existing_source_url: int = 0
    failed: int = 0

    def exit_code(self) -> int:
        return 1 if self.failed > 0 else 0


def run_process_day(
    *,
    config: AppConfig,
    target_date: date,
    yes: bool,
    dry_run: bool,
    no_llm: bool,
    output_mode: str,
    emit: Callable[[str], None],
    ensure_local_llm_if_needed: Callable[[AppConfig], None],
    render_meeting_candidates: Callable[[list[MeetingCandidate], date], None],
    prompt_candidate_indices: Callable[[int], list[int]],
    prompt_folder_choice_for_candidate: Callable[[AppConfig, MeetingCandidate], str],
    find_existing_note_by_source_url: Callable[[Path, str], Path | None],
    run_single_process: Callable[..., int],
    discover_meetings: Callable[[AppConfig, date, str], list[MeetingCandidate]] | None = None,
) -> int:
    timezone_name = config.timezone if config.timezone else "local"
    discover = discover_meetings or _discover_meetings
    try:
        candidates = discover(config, target_date, timezone_name)
    except RetrievalError as exc:
        emit(render_error_message(exc, context="Meeting discovery failed"))
        return exit_code_for_error(exc)

    if not candidates:
        emit(f"No transcript-ready meetings found for {target_date.isoformat()}.")
        return 0

    ensure_local_llm_if_needed(config)
    render_meeting_candidates(candidates, target_date)
    selected_indices = prompt_candidate_indices(len(candidates))
    if not selected_indices:
        emit("No meetings selected.")
        return 0

    summary = _process_selected_candidates(
        config=config,
        candidates=candidates,
        selected_indices=selected_indices,
        yes=yes,
        dry_run=dry_run,
        no_llm=no_llm,
        output_mode=output_mode,
        emit=emit,
        prompt_folder_choice_for_candidate=prompt_folder_choice_for_candidate,
        find_existing_note_by_source_url=find_existing_note_by_source_url,
        run_single_process=run_single_process,
    )
    _emit_summary(summary, emit=emit)
    return summary.exit_code()


def parse_candidate_selection(value: str, total_candidates: int) -> list[int] | None:
    cleaned = value.strip().lower()
    if not cleaned:
        return []
    if cleaned == "all":
        return list(range(total_candidates))

    selected: set[int] = set()
    for chunk in cleaned.split(","):
        part = chunk.strip()
        if not part:
            return None
        if "-" in part:
            pieces = part.split("-", 1)
            if len(pieces) != 2 or not pieces[0].isdigit() or not pieces[1].isdigit():
                return None
            start = int(pieces[0])
            end = int(pieces[1])
            if start <= 0 or end <= 0 or end < start:
                return None
            if end > total_candidates:
                return None
            for idx in range(start, end + 1):
                selected.add(idx - 1)
            continue
        if not part.isdigit():
            return None
        idx = int(part)
        if idx <= 0 or idx > total_candidates:
            return None
        selected.add(idx - 1)
    return sorted(selected)


def _process_selected_candidates(
    *,
    config: AppConfig,
    candidates: list[MeetingCandidate],
    selected_indices: list[int],
    yes: bool,
    dry_run: bool,
    no_llm: bool,
    output_mode: str,
    emit: Callable[[str], None],
    prompt_folder_choice_for_candidate: Callable[[AppConfig, MeetingCandidate], str],
    find_existing_note_by_source_url: Callable[[Path, str], Path | None],
    run_single_process: Callable[..., int],
) -> DayProcessingSummary:
    processed = 0
    failed = 0
    skipped_existing = 0
    for index in selected_indices:
        candidate = candidates[index]
        folder_choice = prompt_folder_choice_for_candidate(config, candidate)
        granola_link = candidate.source_url
        duplicate_path = find_existing_note_by_source_url(config.vault_root, granola_link)
        if duplicate_path is not None:
            skipped_existing += 1
            log_event(
                command="process_day",
                source_url=granola_link,
                action="skipped_existing_source_url",
                output_path=str(duplicate_path),
            )
            emit(f"Skipped duplicate source_url. Existing note: {duplicate_path}")
            continue
        exit_code = run_single_process(
            config=config,
            granola_link=granola_link,
            folder_choice=folder_choice,
            confirm_write=not yes,
            dry_run=dry_run,
            no_llm=no_llm,
            output_mode=output_mode,
            command_name="process_day",
        )
        if exit_code == 0:
            processed += 1
        else:
            failed += 1

    return DayProcessingSummary(
        selected=len(selected_indices),
        processed=processed,
        skipped_existing_source_url=skipped_existing,
        failed=failed,
    )


def _emit_summary(summary: DayProcessingSummary, *, emit: Callable[[str], None]) -> None:
    emit("Day processing summary:")
    emit(f"- selected: {summary.selected}")
    emit(f"- processed: {summary.processed}")
    emit(f"- skipped_existing_source_url: {summary.skipped_existing_source_url}")
    emit(f"- failed: {summary.failed}")


def _discover_meetings(config: AppConfig, target_date: date, timezone_name: str) -> list[MeetingCandidate]:
    return list_meetings_for_day(
        config,
        target_date,
        timezone_name=timezone_name,
    )
