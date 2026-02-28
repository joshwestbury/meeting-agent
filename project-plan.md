# Meeting Agent: Project Plan (v1)

> Granola meeting link -> local CLI agent -> Obsidian vault (`~/Documents/Alter Mentis Obsidian Vault`)

This project builds a local-first CLI workflow that accepts a Granola meeting link, retrieves the transcript, generates a structured Markdown note, and writes it to your Obsidian vault.

**Assumptions:** macOS, Python 3.12+, `uv`, Granola account access, authenticated retrieval method available.

---

## Scope (v1)

`meeting-agent` (interactive) should:
1. Prompt for Granola meeting link.
2. Validate link format and extract meeting ID.
3. Retrieve transcript to local staging.
4. Prompt for destination directory inside vault.
5. Generate a normalized meeting note (frontmatter + sections).
6. Validate output against strict rules.
7. Write note to the selected vault directory.
8. Record state so reruns are idempotent.

`meeting-agent process <granola_link>` (non-interactive) should:
1. Accept link as argument.
2. Accept destination via `--folder` (or prompt if missing).
3. Perform the same retrieval, generation, validation, write, and state flow.

Batch mode (`meeting-agent process --new`) remains in scope for processing unprocessed/changed staged transcripts.

---

## Phase 0: CLI UX and Configuration

### 0.1 Primary command surface

| Command | Behavior |
|---|---|
| `meeting-agent` | Start interactive flow (prompt link, prompt folder, preview, confirm, write) |
| `meeting-agent init` | One-time setup for vault root, staging path, and auth config |
| `meeting-agent process <granola_link>` | One-shot processing from link; prompts for missing options |
| `meeting-agent process --new` | Process all unprocessed/changed staged transcripts |
| `meeting-agent open --latest` | Open last successfully written note |

### 0.2 Interactive flow (resolved)

When user runs `meeting-agent`, the CLI must execute:
1. Prompt: `Granola meeting link:`
2. Validate link, extract `meeting_id`.
3. Prompt: `Destination folder (vault-relative):`
4. Validate folder is safe and under vault root.
5. Retrieve transcript and build proposed note metadata.
6. Show preview:
   - Meeting title/date (derived)
   - Target folder
   - Filename
   - Full output path
7. Prompt for final confirmation: `Write note? [y/N]`
8. On confirm, write note and state; on decline, abort with no writes.

### 0.3 Config keys (required)

Persist in `~/.config/meeting-agent/config.toml`:
- `vault_root` (absolute path; default `~/Documents/Alter Mentis Obsidian Vault`)
- `staging_root` (absolute path; default `~/granola-export`)
- `default_folder` (optional vault-relative folder)
- `timezone` (IANA name or `local`)
- `auth_mode` (`token`, `cookie`, or `manual_export`)

Startup validation must fail fast if:
- `vault_root` does not exist
- `vault_root` is not writable
- `staging_root` cannot be created/written
- auth config is missing for selected retrieval mode

---

## Phase 1: Validate Ingestion

### 1.1 Source of truth

Use Granola meeting link as the primary v1 ingestion trigger, with local staging as the durable transcript store.

**Blocking check:**
1. Confirm reliable retrieval method exists for a meeting URL (API/export/manual flow).
2. Confirm retrieved payload contains transcript text and stable metadata (especially `granola_id`/meeting ID).
3. Confirm retrieved transcript can be written to staging consistently.

### 1.2 Link parsing and selection contract (resolved)

Accepted input formats:
- `https://notes.granola.ai/t/<meeting-uuid>-<suffix>`
- Future-safe: URL with query params/fragments should still parse base meeting ID.

Selection behavior:
1. `meeting-agent process <granola_link>` uses the exact provided meeting link.
2. `meeting-agent` interactive prompts for exactly one link and processes that link.
3. `process --latest` (if retained) selects latest staged transcript by:
   - `mtime` descending
   - tie-breaker: filename ascending
4. Ignore files modified in the last 10 seconds to avoid partial writes.
5. If no eligible transcript is found for `--latest`, exit non-zero with actionable message.

**If `granola_id` is unavailable from retrieval payload:**
- Use `transcript_hash` as the canonical identity key.
- Derive `source_key = sha256(normalized_transcript_text)` for dedup and updates.
- Keep `granola_id: ""` in frontmatter/state for schema compatibility.

### 1.3 Staging layout

```text
~/granola-export/
  transcripts/
  failed-notes/
  retrieval-cache/
```

`failed-notes/` is outside the vault and is used for quarantine artifacts.
`retrieval-cache/` stores raw API/export payloads for troubleshooting when enabled.

---

## Phase 2: Obsidian Note Contract

### 2.1 Destination folder policy

The writer may target any vault-relative folder provided by the user, but must enforce safety rules.

Recommended folders:

| Folder | When to use |
|---|---|
| `Work/Meetings/Clients/<Client>/` | Client context detected |
| `Work/Meetings/Internal/` | Internal/work context detected |
| `Personal/Meetings/` | Personal context detected |
| `Inbox/Meetings/` | Fallback when uncertain |

All paths are relative to `vault_root` (`~/Documents/Alter Mentis Obsidian Vault` by default).

Folder validation rules:
1. Input must be vault-relative (no absolute path input).
2. Normalize and resolve path; resulting path must remain under `vault_root`.
3. Reject traversal attempts (`..`, symlink escape, encoded traversal).
4. Auto-create folder if missing (with `mkdir -p`) after validation.
5. If creation fails, abort with actionable error.

### 2.2 Naming scheme

Primary filename:

```text
YYYY-MM-DD - <Title>.md
```

If multiple meetings share date/title:

```text
YYYY-MM-DD HHmm - <Title>.md
```

### 2.3 Collision policy (resolved)

1. If existing note has same `granola_id`: update in place.
2. Else if same `transcript_hash`: skip as duplicate.
3. Else: do not overwrite; quarantine and log as collision.

No silent `(2)`/`(3)` suffixing.

**Fallback when `granola_id` is missing:**
1. If existing note has same `transcript_hash`: update in place.
2. Else: quarantine as collision (no overwrite).

### 2.4 Write location contract (resolved)

Output path computation:
1. Take validated `vault_root`.
2. Take validated user folder input (vault-relative).
3. Compute filename from naming scheme.
4. Join into `output_path = vault_root / folder / filename`.
5. Resolve `output_path`; verify still under `vault_root` before write.
6. Write atomically (`.tmp` then rename).

### 2.5 Required frontmatter

```yaml
---
type: meeting
source: granola
source_url: "https://notes.granola.ai/t/..."
meeting_date: 2026-02-28
attendees: []
client: ""
project: ""
tags: [meeting]
granola_id: ""
transcript_hash: ""
created: 2026-02-28T09:12:00-06:00
needs_review: false
sensitive: false
vault_folder: "Work/Meetings/Clients/Acme/"
---
```

---

## Phase 3: Identity and State

State file:

```text
~/.config/meeting-agent/state.json
```

Per transcript entry:
- `granola_id` (primary identity key when available)
- `transcript_hash` (secondary identity key)
- `source_key` (required; `granola_id` if present, else normalized-text hash)
- `source_url`
- `transcript_path` (metadata only, non-identity)
- `last_processed_at` (ISO 8601)
- `output_path`
- `status` (`processed`, `quarantined`, `skipped`)

### 3.1 State safety

- Single-writer lock file to prevent concurrent runs.
- Atomic state writes (`state.json.tmp` then rename).
- On state-write failure, do not mark transcript as processed.

### 3.2 Timezone policy

- Store `created` as timezone-aware local timestamp (`YYYY-MM-DDTHH:mm:ss±HH:MM`).
- Compute `meeting_date` in local timezone.
- Use the same local timezone basis for filename date stamps and "latest" logs.

---

## Phase 4: Retrieval and CLI Behavior

**Stack:** Python + `uv` + Typer

### 4.1 Retrieval flow

For `meeting-agent` and `process <granola_link>`:
1. Parse and validate Granola URL.
2. Retrieve transcript via configured `auth_mode`.
3. Normalize transcript text.
4. Persist staged transcript at `~/granola-export/transcripts/<meeting_id>.txt`.
5. Continue to formatting/routing/write pipeline.

### 4.2 Retrieval error categories

Must map failures to explicit user-facing errors:
- `AUTH_REQUIRED` (missing/expired auth)
- `NOT_FOUND` (meeting missing or inaccessible)
- `RATE_LIMITED`
- `NETWORK_ERROR`
- `PARSE_ERROR` (payload structure unexpected)

### 4.3 CLI options

`meeting-agent process` supports:
- positional: `<granola_link>`
- `--folder <vault-relative-folder>`
- `--yes` (skip final confirmation)
- `--dry-run` (no writes, show resolved output path/metadata)
- `--no-llm`
- `--force-sensitive`

---

## Phase 5: Agent Pipeline

### 5.1 Authority boundary (resolved)

- LLM returns structured JSON only.
- Local Python code validates JSON and writes files.
- LLM has no file-write tool access in v1.

### 5.2 LLM output contract

Expected fields:
- `title`
- `meeting_date`
- `attendees`
- `client`
- `project`
- `tags`
- `folder_choice` (must be from provided candidates)
- `summary`
- `action_items`
- `key_details`
- `decisions` (optional)
- `open_questions` (optional)
- `sensitive` (boolean)

### 5.3 Guardrails (non-negotiable)

- Folder must resolve under vault root.
- Filename sanitized and traversal-safe.
- Frontmatter schema must validate before write.
- Max note length enforced.
- Collisions handled by policy in 2.3.

---

## Phase 6: Routing Logic

Two-layer routing:

### Layer A: deterministic candidates

Generate candidate folders from rules:
- internal keywords -> `Work/Meetings/Internal/`
- client match -> `Work/Meetings/Clients/<Client>/`
- personal keywords -> `Personal/Meetings/`
- always include fallback -> `Inbox/Meetings/`

### Layer B: LLM selection

LLM picks exactly one folder from candidates and returns a short reason (for logs).

### Layer C: user override (interactive)

If user supplied folder in prompt or `--folder`, that folder is authoritative after safety validation.

---

## Phase 7: Output Format

### 7.1 Required body sections

Always include:
- `## Summary`
- `## Action Items`
- `## Key Details`

Include only when content exists:
- `## Decisions`
- `## Open Questions`

### 7.2 Transcript linking

Raw transcripts stay in staging. Use a standard Markdown link, not a wiki link:

```md
Full transcript: [transcript.txt](file:///Users/<you>/granola-export/transcripts/transcript.txt)
```

**Validation gate before locking this in:**
- Test `file:///` link behavior in Obsidian with a real staged transcript.
- If behavior is inconsistent, switch to copying transcripts into vault storage (for example `Assets/Transcripts/`) and link vault-relative paths.

---

## Phase 8: Privacy and Safe Mode

### 8.1 `--no-llm` mode

Add a deterministic fallback that creates a template note with transcript link and metadata only.

### 8.2 Sensitive handling

If transcript is flagged `sensitive: true`:
- Skip LLM summarization.
- Write minimal note with `needs_review: true`.
- Route to `Inbox/Meetings/` for manual handling.

### 8.3 Sensitive flag source (pre-LLM)

Set `sensitive: true` before any LLM call using deterministic rules:
- Keyword match list (for example: SSN patterns, bank account terms, legal/medical markers).
- Optional user-maintained allow/deny term files in config.
- Optional `--force-sensitive` CLI override.

If any rule matches, bypass LLM and follow 8.2.

---

## Error Handling and Quarantine

### `--latest`
- Fail fast and print actionable error.

### `--new`
- Quarantine failing items and continue remaining transcripts.

### Interactive or one-shot link mode
- Retrieval or validation failure: fail fast before any vault write.
- Confirmation declined: graceful abort with no writes.

Quarantine artifacts go to:

```text
~/granola-export/failed-notes/
```

Store failing payload, validation errors, and attempted metadata for debugging.

## Logging

Write structured logs to:

```text
~/.config/meeting-agent/meetings.log
```

Each entry should include:
- `timestamp`
- `command` (`meeting-agent`, `process <link>`, `process --new`, etc.)
- `source_key`
- `source_url`
- `transcript_path`
- `action` (`processed`, `skipped`, `updated`, `quarantined`, `failed`)
- `folder_choice`
- `folder_reason`
- `output_path`
- `error` (if any)

---

## Acceptance Criteria (v1)

v1 is done when:

1. `meeting-agent` prompts for link and folder, then writes a valid note under `vault_root`.
2. Re-running on unchanged transcript does not duplicate output.
3. `meeting-agent process <granola_link>` works non-interactively with `--folder`.
4. `meeting-agent process --new` processes all pending transcripts and continues past individual failures.
5. Link parsing, retrieval, and error mapping behave as specified.
6. Every successful note has valid frontmatter and required sections.
7. Invalid folder, filename, or schema output is blocked before write.
8. Collisions follow policy in 2.3.
9. State writes are atomic and protected by a lock.
10. `--no-llm` path works end-to-end.
11. Resolved output path is always inside `vault_root`.

---

## Implementation Order

1. Validate Granola export reliability and metadata shape.
2. Build `meeting-agent init` config flow (`vault_root`, staging, auth mode).
3. Scaffold Typer CLI with interactive default command and `process` subcommands.
4. Implement Granola URL parser + retrieval layer + staged transcript writer.
5. Implement state store (lock + atomic writes).
6. Implement routing, folder/path safety checks, and validation layer.
7. Add LLM JSON generation and parser.
8. Add writer + quarantine flow with atomic note writes.
9. Run end-to-end tests on real transcripts and tune prompts.
