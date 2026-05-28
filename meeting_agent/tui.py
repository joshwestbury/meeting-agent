from datetime import date
from collections.abc import Callable
from pathlib import Path
import textwrap

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, ListItem, ListView, Static

from meeting_agent.config import AppConfig
from meeting_agent.errors import RetrievalError
from meeting_agent.exit_codes import render_error_message
from meeting_agent.retrieval import MeetingCandidate, list_meetings_for_day


ProcessMeetingCallback = Callable[[MeetingCandidate, Callable[[str], None], str | None], None]
ExistingNoteCallback = Callable[[MeetingCandidate], Path | None]
IMPORT_ALL_ID = "import-all"


class MeetingAgentTui(App[MeetingCandidate | None]):
    CSS = """
    Screen {
        background: transparent;
        color: #d5d9e2;
        align: center middle;
    }

    #picker {
        width: 96;
        height: 18;
        min-width: 72;
        min-height: 15;
        padding: 0;
        background: transparent;
    }

    #panes {
        height: 1fr;
        margin-bottom: 1;
    }

    #results-pane {
        width: 56%;
        min-width: 36;
        border: round #b7c0cc;
        background: transparent;
        margin-right: 1;
    }

    #preview-pane {
        width: 1fr;
        border: round #b7c0cc;
        background: transparent;
    }

    .pane-title {
        height: 1;
        padding: 0 1;
        color: #d5d9e2;
        text-style: bold;
    }

    ListView {
        height: 1fr;
        background: transparent;
    }

    ListItem {
        padding: 0 1;
        color: #d5d9e2;
    }

    ListItem.--highlight {
        background: #5b626d;
        color: #f8fafc;
    }

    #details {
        height: 1fr;
        padding: 1 1;
        background: transparent;
    }

    #output-row {
        height: 4;
        border: round #b7c0cc;
        background: transparent;
    }

    #output {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        background: transparent;
        color: #aeb7c5;
    }

    #folder-label {
        width: 11;
        display: none;
        content-align: right middle;
        color: #d5d9e2;
        text-style: bold;
    }

    #folder-label.visible {
        display: block;
    }

    #folder-input {
        width: 1fr;
        display: none;
        background: transparent;
        border: none;
        color: #d5d9e2;
        padding: 0 1;
    }

    #folder-input.visible {
        display: block;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: transparent;
        color: #8f98a8;
    }
    """
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("p", "process", "Process"),
        ("enter", "process", "Process"),
        ("o", "open_source", "Open source"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        app_config: AppConfig,
        day: date,
        *,
        process_meeting: ProcessMeetingCallback | None = None,
        existing_note_for_candidate: ExistingNoteCallback | None = None,
    ) -> None:
        super().__init__()
        self.config = app_config
        self.target_date = day
        self.process_meeting = process_meeting
        self.existing_note_for_candidate = existing_note_for_candidate
        self.candidates: list[MeetingCandidate] = []
        self.existing_note_paths: dict[int, Path] = {}
        self.selected_index: int | None = None
        self.output_lines: list[str] = []
        self.is_processing = False
        self.import_all_queue: list[MeetingCandidate] = []
        self.import_all_total = 0
        self.awaiting_folder_candidate: MeetingCandidate | None = None
        self.title = "Meeting Agent"
        self.sub_title = day.isoformat()

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            with Horizontal(id="panes"):
                with Vertical(id="results-pane"):
                    yield Static(self._meeting_title(), classes="pane-title")
                    yield ListView(id="meeting-list")
                with Vertical(id="preview-pane"):
                    yield Static("Meeting Preview", classes="pane-title")
                    yield Static(self._empty_details(), id="details")
            with Horizontal(id="output-row"):
                yield Static("", id="output")
                yield Static("Folder >", id="folder-label")
                yield Input(placeholder="Destination folder", id="folder-input")
            yield Static("↑/↓ select   enter process   import all row for batch   o source   r refresh   q quit", id="status")

    async def on_mount(self) -> None:
        self.query_one("#results-pane", Vertical).border_title = " Meetings "
        self.query_one("#preview-pane", Vertical).border_title = " Preview "
        self.query_one("#output-row", Horizontal).border_title = " Output "
        await self._refresh_candidates()
        self.query_one("#meeting-list", ListView).focus()

    @on(ListView.Highlighted, "#meeting-list")
    def _update_details_for_highlight(self, event: ListView.Highlighted) -> None:
        if event.item is None:
            return
        item_id = event.item.id or ""
        if item_id == IMPORT_ALL_ID:
            self.selected_index = len(self.candidates)
            self._render_details()
            self._render_status()
            return
        if not item_id.startswith("meeting-"):
            return
        self.selected_index = int(item_id.removeprefix("meeting-"))
        self._render_details()
        self._render_status()

    @on(ListView.Selected, "#meeting-list")
    def _process_selected_list_item(self, _event: ListView.Selected) -> None:
        self.action_process()
    async def action_refresh(self) -> None:
        await self._refresh_candidates()

    def action_process(self) -> None:
        if self.awaiting_folder_candidate is not None:
            self.query_one("#folder-input", Input).focus()
            return
        if self._selected_is_import_all():
            self._start_import_all()
            return
        candidate = self._selected_candidate()
        if candidate is None:
            self._write_output("No meeting selected.")
            return
        if self.is_processing:
            self._write_output("Already processing a meeting.")
            return
        existing_path = self.existing_note_paths.get(self.selected_index)
        if existing_path is not None:
            self._write_output("Skipped duplicate source_url.")
            self._write_output(f"Existing note: {self._display_path(existing_path)}")
            return
        self._write_output(f"Processing: {candidate.title or candidate.meeting_id}")
        if self.process_meeting is None:
            self.exit(candidate)
            return
        self.is_processing = True
        self.is_processing = False
        self.import_all_total = 0
        self.awaiting_folder_candidate = candidate
        self._prompt_folder_for_candidate(candidate, prefix="Destination folder")

    def action_open_source(self) -> None:
        if self._selected_is_import_all():
            self._write_output("Import all will process every unimported meeting.")
            return
        candidate = self._selected_candidate()
        if candidate is None:
            self._write_output("No meeting selected.")
            return
        self._write_output(candidate.source_url)

    async def _refresh_candidates(self) -> None:
        status = self.query_one("#status", Static)
        list_view = self.query_one("#meeting-list", ListView)
        details = self.query_one("#details", Static)
        status.update(f"Discovering transcript-ready meetings for {self.target_date.isoformat()}...")
        self.output_lines = []
        self._render_output()
        details.update("Loading meetings...")
        await list_view.clear()
        self.candidates = []
        self.existing_note_paths = {}
        self.selected_index = None
        self._render_status()

        timezone_name = self.config.timezone if self.config.timezone else "local"
        try:
            candidates = list_meetings_for_day(self.config, self.target_date, timezone_name=timezone_name)
        except RetrievalError as exc:
            details.update("Meeting discovery failed.")
            status.update("Discovery failed. r refresh   q quit")
            self._write_output(render_error_message(exc, context="Meeting discovery failed"))
            if exc.code == "auth_required":
                self._write_output("Try: meeting-agent auth-import")
            return

        self.candidates = candidates
        self.existing_note_paths = self._resolve_existing_note_paths(candidates)
        if not candidates:
            details.update(f"No transcript-ready meetings found for {self.target_date.isoformat()}.")
            status.update("No meetings found. r refresh   q quit")
            return

        await self._populate_list()
        list_view.focus()
        status.update("↑/↓ select   enter process   o source   r refresh   q quit")
        self._write_output(f"Loaded {len(candidates)} meeting(s). Use ↑/↓, then Enter to process.")

    async def _populate_list(self) -> None:
        list_view = self.query_one("#meeting-list", ListView)
        await list_view.clear()
        self.selected_index = None
        for candidate_index in range(len(self.candidates)):
            label = self._candidate_label(self.candidates[candidate_index])
            await list_view.append(ListItem(Label(label), id=f"meeting-{candidate_index}"))
        await list_view.append(ListItem(Label(self._import_all_label()), id=IMPORT_ALL_ID))
        if self.candidates:
            list_view.index = 0
            self.selected_index = 0
            self._render_details()
        else:
            self.query_one("#details", Static).update(self._empty_details())
        self._render_status()

    def _render_details(self) -> None:
        details = self.query_one("#details", Static)
        if self._selected_is_import_all():
            total = len(self._unimported_candidates())
            details.update(
                "\n".join(
                    [
                        "[bold]Import all unimported meetings[/bold]",
                        "",
                        f"Ready to import: {total}",
                        f"Already imported: {len(self.existing_note_paths)}",
                        "",
                        "Enter starts a folder prompt for each meeting.",
                    ]
                )
            )
            return
        candidate = self._selected_candidate()
        if candidate is None:
            details.update(self._empty_details())
            return
        lines = [
            f"[bold]{candidate.title or 'Untitled meeting'}[/bold]",
            "",
            f"Started: {candidate.started_at or 'unknown time'}",
            f"Meeting ID: {candidate.meeting_id}",
        ]
        existing_path = self.existing_note_paths.get(self.selected_index)
        if existing_path is not None:
            lines.extend(["", "[bold]Already imported[/bold]", self._display_path(existing_path)])
        details.update("\n".join(lines))

    def _selected_candidate(self) -> MeetingCandidate | None:
        if self.selected_index is None:
            return None
        if self.selected_index < 0 or self.selected_index >= len(self.candidates):
            return None
        return self.candidates[self.selected_index]

    def _selected_is_import_all(self) -> bool:
        return self.selected_index == len(self.candidates) and bool(self.candidates)

    def _meeting_title(self) -> str:
        return f"Meetings  {self.target_date.isoformat()}"

    def _empty_details(self) -> str:
        return "Select a meeting to see its details."

    def _candidate_label(self, candidate: MeetingCandidate) -> str:
        title = candidate.title or "Untitled meeting"
        started = candidate.started_at or "unknown time"
        duplicate_marker = ""
        for index, current in enumerate(self.candidates):
            if current is candidate and index in self.existing_note_paths:
                duplicate_marker = "  [imported]"
                break
        return f"> {started}  {title}{duplicate_marker}"

    def _import_all_label(self) -> str:
        return f"> Import all unimported meetings ({len(self._unimported_candidates())})"

    def _selection_label(self) -> str:
        total = len(self.candidates)
        if self._selected_is_import_all():
            return "selected import all"
        selected = 0 if self.selected_index is None else self.selected_index + 1
        return f"selected meeting {selected} of {total}"

    def _render_status(self) -> None:
        self.query_one("#status", Static).update(
            f"{self._selection_label()}   ↑/↓ select   enter process   o source   r refresh   q quit"
        )

    def _write_output(self, message: str) -> None:
        self.output_lines.extend(self._wrap_output_message(message))
        self.output_lines = self.output_lines[-3:]
        self._render_output()

    def _wrap_output_message(self, message: str) -> list[str]:
        return textwrap.wrap(message, width=78, break_long_words=False) or [""]

    def _display_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.config.vault_root.resolve()).as_posix()
        except ValueError:
            return str(path)

    def _resolve_existing_note_paths(self, candidates: list[MeetingCandidate]) -> dict[int, Path]:
        if self.existing_note_for_candidate is None:
            return {}
        existing: dict[int, Path] = {}
        for index, candidate in enumerate(candidates):
            path = self.existing_note_for_candidate(candidate)
            if path is not None:
                existing[index] = path
        return existing

    def _render_output(self) -> None:
        self.query_one("#output", Static).update("\n".join(self.output_lines))

    def _process_candidate_in_worker(self, candidate: MeetingCandidate, folder_choice: str | None) -> None:
        success = False
        try:
            if self.process_meeting is not None:
                self.process_meeting(
                    candidate,
                    lambda message: self.call_from_thread(self._write_output, message),
                    folder_choice,
                )
                success = True
        except Exception as exc:
            self.call_from_thread(self._write_output, f"Processing failed: {exc}")
        finally:
            self.call_from_thread(self._finish_processing, success)

    def _finish_processing(self, success: bool = False) -> None:
        self.is_processing = False
        if self.import_all_queue:
            self._prompt_next_import_all_folder()
            return
        if self.import_all_total:
            self.import_all_total = 0
            self._hide_folder_input()
            self._write_output("Import all complete.")
            return
        if success:
            self._write_output("Done.")

    def _unimported_candidates(self) -> list[MeetingCandidate]:
        return [candidate for index, candidate in enumerate(self.candidates) if index not in self.existing_note_paths]

    def _start_import_all(self) -> None:
        if self.is_processing:
            self._write_output("Already processing a meeting.")
            return
        self.import_all_queue = self._unimported_candidates()
        self.import_all_total = len(self.import_all_queue)
        if not self.import_all_queue:
            self._write_output("No unimported meetings to import.")
            return
        self._write_output(f"Importing {self.import_all_total} meeting(s).")
        self._prompt_next_import_all_folder()

    def _prompt_next_import_all_folder(self) -> None:
        if not self.import_all_queue:
            self.awaiting_folder_candidate = None
            self._hide_folder_input()
            self._write_output("Import all complete.")
            return
        candidate = self.import_all_queue.pop(0)
        self.awaiting_folder_candidate = candidate
        position = self.import_all_total - len(self.import_all_queue)
        self._write_output(f"Folder [{position}/{self.import_all_total}]: {candidate.title or candidate.meeting_id}")
        self._show_folder_input()

    def _prompt_folder_for_candidate(self, candidate: MeetingCandidate, *, prefix: str) -> None:
        self._write_output(f"{prefix}: {candidate.title or candidate.meeting_id}")
        self._show_folder_input()

    def _show_folder_input(self) -> None:
        default_folder = self.config.default_folder or "Inbox/"
        self.query_one("#output-row", Horizontal).border_title = " Destination Folder "
        self.query_one("#status", Static).update("type folder name or path   enter import   esc/q cancel")
        self._write_output(f"Type destination folder, then press Enter. Default: {default_folder}")
        folder_label = self.query_one("#folder-label", Static)
        folder_label.add_class("visible")
        folder_input = self.query_one("#folder-input", Input)
        folder_input.value = ""
        folder_input.placeholder = default_folder
        folder_input.add_class("visible")
        folder_input.focus()

    def _hide_folder_input(self) -> None:
        self.query_one("#output-row", Horizontal).border_title = " Output "
        self.query_one("#status", Static).update("↑/↓ select   enter process   o source   r refresh   q quit")
        folder_label = self.query_one("#folder-label", Static)
        folder_label.remove_class("visible")
        folder_input = self.query_one("#folder-input", Input)
        folder_input.remove_class("visible")
        self.query_one("#meeting-list", ListView).focus()

    @on(Input.Submitted, "#folder-input")
    def _process_import_all_folder(self, event: Input.Submitted) -> None:
        candidate = self.awaiting_folder_candidate
        if candidate is None:
            return
        folder_choice = event.value.strip() or self.config.default_folder or "Inbox/"
        self.awaiting_folder_candidate = None
        self._hide_folder_input()
        self._write_output(f"Destination folder: {folder_choice}")
        self._write_output("Retrieving transcript...")
        self.is_processing = True
        self.run_worker(
            lambda: self._process_candidate_in_worker(candidate, folder_choice),
            name="process-meeting",
            group="process-meeting",
            exclusive=True,
            exit_on_error=False,
            thread=True,
        )


def create_tui_app(
    config: AppConfig,
    *,
    target_date: date,
    process_meeting: ProcessMeetingCallback | None = None,
    existing_note_for_candidate: ExistingNoteCallback | None = None,
) -> MeetingAgentTui:
    return MeetingAgentTui(
        config,
        target_date,
        process_meeting=process_meeting,
        existing_note_for_candidate=existing_note_for_candidate,
    )


def run_tui(
    config: AppConfig,
    *,
    target_date: date,
    process_meeting: ProcessMeetingCallback | None = None,
    existing_note_for_candidate: ExistingNoteCallback | None = None,
) -> MeetingCandidate | None:
    """Run the terminal UI."""
    return create_tui_app(
        config,
        target_date=target_date,
        process_meeting=process_meeting,
        existing_note_for_candidate=existing_note_for_candidate,
    ).run(
        inline=True,
        inline_no_clear=True,
        size=(96, 18),
    )
