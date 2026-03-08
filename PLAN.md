### Plan: Interactive Day-Based Meeting Discovery + Selective Processing

### Summary
Yes, this is feasible.
Add a new CLI flow that discovers meetings with available transcripts for a target day, displays a numbered list, lets you choose items (`1,3-5` / `all`), and then processes only selected meetings using the existing single-meeting processing pipeline.

### Implementation Changes
- Add a new command: `meeting-agent process-day` (name fixed for clarity and separation from `process <link>`).
- Command interface:
  - `--date YYYY-MM-DD` optional.
  - No `--date` means "today" in configured/local timezone.
  - Reuse existing processing flags where applicable (`--yes`, `--dry-run`, `--no-llm`, `--summary`).
- Add remote discovery in retrieval layer:
  - Introduce a typed `MeetingCandidate` model with fields: `document_id`, `meeting_id`, `title`, `started_at`, `has_transcript`, `source_url`.
  - Add `list_meetings_for_day(config, target_date)` that calls Granola discovery endpoint(s), filters to day, and keeps only transcript-available meetings.
  - On discovery failure, return explicit actionable error (no staged fallback).
- Add interactive selection parser:
  - Render numbered candidates with date/time/title.
  - Accept `all` or index expressions (`1,2,4-6`), validate input, reprompt on invalid entries.
- Process selected items by converting each candidate to a canonical Granola URL and invoking existing `_run_single_process` path unchanged for write/state/idempotency behavior.

### Public Interfaces / Types
- New CLI command: `process-day`.
- New retrieval API: `list_meetings_for_day(...) -> list[MeetingCandidate]`.
- New type: `MeetingCandidate` (retrieval module), used by CLI selection flow.

### Test Plan
- CLI command behavior:
  - defaults to today when `--date` omitted.
  - respects `--date` override.
  - exits cleanly with message when no transcript-ready meetings found.
- Selection UX:
  - valid inputs: `all`, `1`, `1,3-4`.
  - invalid/repeated/out-of-range input handling.
- Processing integration:
  - selected meetings call existing processing flow exactly once per selection.
  - unselected meetings are not processed.
  - existing `--dry-run`, `--summary`, `--no-llm`, `--yes` behavior still works.
- Failure handling:
  - discovery/auth/API failures map to actionable non-zero exit.
  - per-item processing failures continue and summarize results (same style as batch behavior if desired).

### Assumptions and Defaults
- Target behavior is interactive selection, not automatic processing of all meetings.
- Date behavior is fixed to: default today + optional `--date`.
- Discovery failure policy is fixed to hard fail with actionable error.
- Selection input format is fixed to numbered list with comma/range support.
- Granola meeting discovery uses authenticated API endpoints available to current auth modes (`token`, `cookie`, `desktop_session`); `manual_export` mode will return an explicit "unsupported for remote discovery" error.
