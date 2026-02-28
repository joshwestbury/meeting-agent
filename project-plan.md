# Meeting Agent: Project Plan (v1)

> Granola export -> local CLI agent -> Obsidian vault (`~/Documents/Alter Mentis`)

This project builds a local-first CLI workflow that fetches meeting transcripts from Granola exports, generates structured Markdown notes, and writes them to your Obsidian vault.

**Assumptions:** macOS, Python 3.12+, `uv`, Granola Basic plan.

---

## Scope (v1)

`meetings process --latest` should:
1. Read the latest transcript from local staging export.
2. Generate a normalized meeting note (frontmatter + sections).
3. Validate output against strict rules.
4. Write the note into `~/Documents/Alter Mentis` in an allowed folder.
5. Record state so reruns are idempotent.

`meetings process --new` should process all unprocessed/changed transcripts with continue-on-error behavior.

---

## Phase 1: Validate Ingestion

### 1.1 Source of truth

Use local Granola export to staging as the v1 ingestion layer.

**Blocking check:**
1. Confirm a reliable export method exists (CLI or manual export workflow).
2. Confirm exported format and metadata (especially whether `granola_id` is available).
3. Confirm exported files land consistently in a known folder.

**If `granola_id` is unavailable:**
- Use `transcript_hash` as the canonical identity key.
- Derive `source_key = sha256(normalized_transcript_text)` for dedup and updates.
- Keep `granola_id: ""` in frontmatter/state for schema compatibility.

### 1.2 Staging layout

```text
~/granola-export/
  transcripts/
  failed-notes/
```

`failed-notes/` is outside the vault and is used for quarantine artifacts.

---

## Phase 2: Obsidian Note Contract

### 2.1 Allowed destination folders

The writer may only target:

| Folder | When to use |
|---|---|
| `Work/Meetings/Clients/<Client>/` | Client context detected |
| `Work/Meetings/Internal/` | Internal/work context detected |
| `Personal/Meetings/` | Personal context detected |
| `Inbox/Meetings/` | Fallback when uncertain |

All paths are relative to `~/Documents/Alter Mentis`.

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

### 2.4 Required frontmatter

```yaml
---
type: meeting
source: granola
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
---
```

---

## Phase 3: Identity and State

State file:

```text
~/.config/meetings-agent/state.json
```

Per transcript entry:
- `granola_id` (primary identity key when available)
- `transcript_hash` (secondary identity key)
- `source_key` (required; `granola_id` if present, else normalized-text hash)
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

## Phase 4: CLI Commands

**Stack:** Python + `uv` + Typer

| Command | Behavior |
|---|---|
| `meetings process --latest` | Process newest transcript by file mtime in `~/granola-export/transcripts/`; fail fast on error |
| `meetings process --new` | Process all unprocessed/changed transcripts; quarantine bad items and continue |
| `meetings open --latest` | Open last successfully written note |

`latest` in v1 is defined strictly as newest transcript file by filesystem mtime.

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

- Folder must be allowlisted and under vault root.
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

Quarantine artifacts go to:

```text
~/granola-export/failed-notes/
```

Store failing payload, validation errors, and attempted metadata for debugging.

## Logging

Write structured logs to:

```text
~/.config/meetings-agent/meetings.log
```

Each entry should include:
- `timestamp`
- `command` (`process --latest`, `process --new`, etc.)
- `source_key`
- `transcript_path`
- `action` (`processed`, `skipped`, `updated`, `quarantined`, `failed`)
- `folder_choice`
- `folder_reason`
- `output_path`
- `error` (if any)

---

## Acceptance Criteria (v1)

v1 is done when:

1. `meetings process --latest` reads latest transcript by mtime and writes a valid note under `~/Documents/Alter Mentis`.
2. Re-running on unchanged transcript does not duplicate output.
3. `meetings process --new` processes all pending transcripts and continues past individual failures.
4. Every successful note has valid frontmatter and required sections.
5. Invalid folder, filename, or schema output is blocked before write.
6. Collisions follow policy in 2.3.
7. State writes are atomic and protected by a lock.
8. `--no-llm` path works end-to-end.

---

## Implementation Order

1. Validate Granola export reliability and metadata shape.
2. Create config for vault root (`~/Documents/Alter Mentis`) and folder allowlist.
3. Scaffold Typer CLI with `process --latest` and `process --new`.
4. Implement state store (lock + atomic writes).
5. Implement deterministic routing and validation layer.
6. Add LLM JSON generation and parser.
7. Add writer + quarantine flow.
8. Run end-to-end tests on real transcripts and tune prompts.
