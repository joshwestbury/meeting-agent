# Meeting Agent Implementation Steps

This document is the execution playbook for implementing everything in `project-plan.md`.
It is ordered for lowest risk and fastest feedback.

## 1) Bootstrapping and Repository Setup

1. Create Python project scaffold with `uv`.
2. Add baseline dependencies:
   - `typer` for CLI
   - `pydantic` for schemas
   - `pyyaml` for frontmatter handling
   - `httpx` for retrieval
   - `python-dateutil` for date parsing
   - `platformdirs` for config/state paths
   - `pytest` for tests
3. Create package layout:

```text
meeting_agent/
  __init__.py
  cli.py
  config.py
  logging.py
  links.py
  retrieval.py
  staging.py
  normalize.py
  llm.py
  routing.py
  note_schema.py
  writer.py
  state.py
  quarantine.py
  errors.py
tests/
```

4. Add `pyproject.toml` scripts:
   - `meeting-agent = "meeting_agent.cli:app"`
5. Add `.gitignore` entries for local artifacts:
   - `.venv/`
   - `.pytest_cache/`
   - temporary test outputs

## 2) Configuration and Init Flow

1. Implement config model in `config.py`:
   - `vault_root: Path`
   - `staging_root: Path`
   - `default_folder: str | None`
   - `timezone: str`
   - `auth_mode: Literal["token", "cookie", "manual_export"]`
2. Config file location:
   - `~/.config/meeting-agent/config.toml`
3. Implement `meeting-agent init`:
   - prompt for each key
   - offer defaults:
     - `vault_root = ~/Documents/Alter Mentis Obsidian Vault`
     - `staging_root = ~/granola-export`
     - `timezone = local`
4. Validate at init-time:
   - `vault_root` exists and writable
   - `staging_root` creatable/writable
   - auth requirements present for selected `auth_mode`
5. Persist config atomically (`config.toml.tmp` then rename).
6. Add startup validator used by all commands.

## 3) Error Taxonomy and Exit Codes

1. Define typed errors in `errors.py`:
   - `ConfigError`
   - `LinkValidationError`
   - `RetrievalError` with code enum:
     - `AUTH_REQUIRED`
     - `NOT_FOUND`
     - `RATE_LIMITED`
     - `NETWORK_ERROR`
     - `PARSE_ERROR`
   - `FolderValidationError`
   - `SchemaValidationError`
   - `CollisionError`
2. Map each to stable CLI exit codes.
3. Implement consistent renderer for user-facing messages.

## 4) Link Parsing and Meeting Identity

1. Implement `links.py`:
   - parse Granola URLs like `https://notes.granola.ai/t/<uuid>-<suffix>`
   - accept query params/fragments but ignore for ID extraction
2. Return structured object:
   - `source_url`
   - `meeting_id` (canonical)
   - `raw_token` (full path token if needed)
3. Add unit tests:
   - valid examples
   - invalid host/path
   - malformed UUID

## 5) Retrieval Layer

1. Implement `retrieval.py` interface:
   - `retrieve_transcript(source_url, config) -> RetrievalResult`
2. `RetrievalResult` contains:
   - `granola_id` (if available)
   - `meeting_id`
   - `title` (if available)
   - `started_at` (if available)
   - `attendees` (if available)
   - `transcript_text`
   - raw payload metadata
3. Implement auth mode handlers:
   - `token`: header-based auth
   - `cookie`: session cookie-based request
   - `manual_export`: deterministic failure with actionable guidance unless local exported data exists
4. Add retry policy for transient failures.
5. Translate transport/API failures into retrieval error codes.
6. Add tests using HTTP mocking:
   - success path
   - each failure category

## 6) Staging and Transcript Normalization

1. Implement staging layout creation:

```text
~/granola-export/
  transcripts/
  failed-notes/
  retrieval-cache/
```

2. Implement `normalize.py`:
   - normalize line endings
   - trim trailing whitespace
   - normalize repeated blank lines
3. Compute hashes:
   - `transcript_hash = sha256(raw_normalized_text)`
   - `source_key = granola_id or sha256(raw_normalized_text)`
4. Persist transcript file:
   - `transcripts/<meeting_id>.txt`
5. Optional cache write:
   - save raw retrieval payload to `retrieval-cache/` when debug enabled

## 7) State Management and Idempotency

1. State location:
   - `~/.config/meeting-agent/state.json`
2. State record fields:
   - `granola_id`
   - `transcript_hash`
   - `source_key`
   - `source_url`
   - `transcript_path`
   - `last_processed_at`
   - `output_path`
   - `status`
3. Implement lock file for single writer.
4. Implement atomic write for state updates.
5. Idempotency rules:
   - if same `granola_id`: update in place
   - else if same `transcript_hash`: skip duplicate
   - else collision path
6. Add unit tests for concurrent lock behavior and atomic safety.

## 8) Folder Validation and Path Safety

1. Implement `routing.py` folder validator:
   - accept vault-relative folder only
   - reject absolute paths
   - reject traversal components
2. Resolve folder against `vault_root`.
3. Verify resolved folder remains under `vault_root`.
4. Create missing directories (`mkdir -p`) only after validation.
5. Add tests:
   - normal folder
   - nested folder
   - `../` traversal attempt
   - symlink escape attempt

## 9) LLM Output Contract and Validation

1. Implement `note_schema.py` with Pydantic model:
   - fields from project plan section 5.2
2. Enforce:
   - required fields present
   - correct types
   - size constraints (max note length)
3. Implement `llm.py`:
   - takes transcript + candidate folders
   - returns structured JSON only
4. Add `--no-llm` fallback:
   - deterministic template note with metadata + transcript link
5. Sensitive pre-check:
   - keyword/pattern scan before LLM
   - if sensitive, bypass LLM and mark `needs_review: true`

## 10) Note Rendering and Frontmatter

1. Implement markdown renderer in `writer.py`:
   - frontmatter + required sections
2. Required frontmatter fields:
   - `type`, `source`, `source_url`, `meeting_date`, `attendees`, `client`, `project`, `tags`, `granola_id`, `transcript_hash`, `created`, `needs_review`, `sensitive`, `vault_folder`
3. Required body sections:
   - `## Summary`
   - `## Action Items`
   - `## Key Details`
4. Optional sections when non-empty:
   - `## Decisions`
   - `## Open Questions`
5. Include transcript link in body.
6. Filename generation:
   - primary: `YYYY-MM-DD - <Title>.md`
   - collision fallback: `YYYY-MM-DD HHmm - <Title>.md`
7. Sanitize filename and enforce safe characters.

## 11) Write Pipeline and Collision Handling

1. Compute output path:
   - `vault_root / validated_folder / filename`
2. Re-resolve and verify path under vault root.
3. Evaluate collision policy:
   - same `granola_id` -> update
   - same `transcript_hash` -> skip
   - otherwise quarantine and log
4. Write note atomically:
   - write `.tmp` file in target dir
   - rename to final
5. On any write failure:
   - do not mark state as processed
   - quarantine diagnostic payload

## 12) Quarantine and Diagnostics

1. Implement `quarantine.py` artifact writer:
   - location: `~/granola-export/failed-notes/`
2. Include:
   - source URL and parsed meeting ID
   - transcript hash/source key
   - attempted folder/output path
   - validation or runtime errors
   - raw payload snapshot (when available)
3. Ensure quarantine writes are best effort and never crash primary error reporting.

## 13) Logging

1. Implement structured logging in `logging.py`.
2. Log file:
   - `~/.config/meeting-agent/meetings.log`
3. Required fields per event:
   - `timestamp`
   - `command`
   - `source_key`
   - `source_url`
   - `transcript_path`
   - `action`
   - `folder_choice`
   - `folder_reason`
   - `output_path`
   - `error`
4. Add log events for:
   - start/end
   - retrieval success/failure
   - schema validation
   - write success/failure
   - quarantine action

## 14) CLI Command Wiring

1. Implement commands in `cli.py`:
   - `meeting-agent` (interactive default)
   - `meeting-agent init`
   - `meeting-agent process <granola_link>`
   - `meeting-agent process --new`
   - `meeting-agent open --latest`
2. Interactive default command flow:
   - prompt link
   - prompt folder
   - retrieve and prepare note
   - preview output path/title/date
   - confirm write
3. `process` options:
   - `--folder`
   - `--yes`
   - `--dry-run`
   - `--no-llm`
   - `--force-sensitive`
4. Ensure identical core pipeline for interactive and non-interactive paths.

## 15) Batch Mode (`process --new`)

1. Scan staged transcripts.
2. Determine eligibility:
   - unprocessed or changed hash
3. For each transcript:
   - run same note generation and write pipeline
4. Continue on per-item failure.
5. Produce run summary:
   - processed
   - updated
   - skipped
   - quarantined
   - failed

## 16) Testing Strategy

1. Unit tests:
   - link parser
   - folder validator
   - filename sanitizer
   - schema validation
   - state lock + atomic writes
2. Integration tests:
   - interactive flow via CLI runner
   - one-shot link processing
   - collision handling behavior
   - sensitive bypass behavior
3. End-to-end tests:
   - mock retrieval + real filesystem temp vault
   - assert final markdown content and metadata
4. Regression fixtures:
   - short transcript
   - long transcript
   - missing metadata
   - malformed payload

## 17) Acceptance Checklist (Must Pass)

1. `meeting-agent` prompts for link and folder and writes note in selected folder.
2. Output path is always inside `vault_root`.
3. Same transcript rerun does not duplicate output.
4. Collision policy behavior matches project plan exactly.
5. `--no-llm` and sensitive paths work end-to-end.
6. `process --new` continues after item failures.
7. State writes are atomic and lock-protected.
8. Structured logs include required fields.
9. Quarantine artifacts are created for failures.

## 18) Suggested Build Order by Milestone

1. Milestone A: Config + CLI skeleton + link parser.
2. Milestone B: Retrieval + staging + normalization + state.
3. Milestone C: Folder safety + writer + collision policy.
4. Milestone D: LLM integration + `--no-llm` + sensitive mode.
5. Milestone E: batch mode + logging + quarantine hardening.
6. Milestone F: full tests + acceptance run on real meetings.

## 19) Definition of Done

1. All acceptance checklist items pass.
2. A full interactive run from Granola link to vault note is successful.
3. Failure paths are recoverable and actionable.
4. Documentation reflects real command behavior and config defaults.
