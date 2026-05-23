---
name: meeting-agent
description: Work on the Meeting Agent repository, a local Python CLI that turns Granola meeting transcripts into structured Obsidian notes. Use when changing CLI behavior, Granola auth or retrieval, transcript processing, LLM summarization, note writing, routing, state handling, model helpers, or tests in this repo.
---

# Meeting Agent

## Project Shape

Meeting Agent is a local-first Python CLI. It retrieves or stages Granola transcripts, optionally summarizes them through a local OpenAI-compatible LLM server, and writes structured Markdown notes into an Obsidian vault.

Primary code lives in `meeting_agent/`. Tests live in `tests/`. The package is managed by `uv`, exposes `meeting-agent` and `ma`, and requires Python 3.12+.

## Workflow

Start by reading the relevant module and the matching tests before editing. Prefer the existing module boundaries:

- `cli.py`: Typer command surface and interactive flows.
- `auth.py`: Granola auth modes, desktop session import, refresh, and keychain handling.
- `retrieval.py`: Granola API retrieval.
- `pipeline.py`: processing orchestration.
- `llm.py` and `note_schema.py`: structured LLM output and validation.
- `writer.py`, `routing.py`, `state.py`, and `staging.py`: vault output, folder resolution, idempotency, and staged transcript handling.

Keep changes scoped to the feature or bug. Preserve local-first behavior and avoid adding network calls or external services unless the user explicitly asks.

## Commands

Use focused tests while iterating:

```bash
uv run pytest tests/test_auth.py
uv run pytest tests/test_cli_process_day.py
uv run pytest tests/test_pipeline.py
```

Run the full suite before broad or cross-module changes:

```bash
uv run pytest
```

Run the CLI through `uv`:

```bash
uv run ma
uv run ma --date YYYY-MM-DD
uv run meeting-agent process "<granola_link>" --yes
```

## Implementation Notes

Maintain deterministic behavior for `--no-llm`, manual export mode, and duplicate detection. New workflows should be safe to rerun and should not corrupt existing vault notes or state.

When changing auth, include tests for expired tokens, refresh failures, keychain interactions, and desktop-session import edge cases. Avoid leaking tokens in logs or error output.

When changing meeting selection, cover interactive input parsing, empty selections, invalid input, skipped duplicates, and multiple selected meetings in tests.

When changing note output, update writer or schema tests and preserve YAML frontmatter compatibility for Obsidian.
