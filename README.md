# Meeting Agent

Local CLI for turning Granola meeting transcripts into structured Obsidian notes.

## What this tool does

Meeting Agent is a **local-first workflow** that connects your [Granola](https://www.granola.ai/) meetings to an **Obsidian vault**. It fetches (or loads) transcript text, optionally runs a **local LLM** to extract a structured summary, and writes a **Markdown note** with YAML frontmatter suitable for search, linking, and daily review.

**End-to-end flow**

1. **Transcripts** — You provide a Granola meeting link, pick from meetings discovered for a given day, or process transcripts already staged on disk. Depending on configuration, transcripts come from Granola’s API (with your credentials) or from a **manual export** layout under your configured staging directory.
2. **Structured content** — By default, a local **llama.cpp**-compatible server generates JSON that is validated against a fixed schema: title, date, attendees, client/project, tags, folder choice, summary, action items, key details, optional decisions and open questions, and a sensitive flag. You can skip the model with `--no-llm` and get a deterministic template instead.
3. **Vault output** — Notes are written under your vault root with metadata such as `source_url`, `granola_id`, `transcript_hash`, and `vault_folder`. Default output includes a **full transcript** section after the structured sections; `--summary` keeps only the summary-style sections.
4. **Safety and repeat runs** — The tool tracks what was written, skips duplicates when the same source URL already has a note, and handles idempotency and collision edge cases so re-running the same meeting does not corrupt your vault.

**Why use it**

- Keep meeting knowledge in **your** Obsidian vault with consistent frontmatter and section layout.
- Prefer **local inference** (configurable GGUF models and `meeting-agent models` helpers) so transcript text does not need to leave your machine for summarization—unless you choose `llm_mode = "none"` or `--no-llm`.
- **One command** (`ma` / `meeting-agent` with no subcommand) runs the interactive “today’s meetings” flow: discover transcript-ready meetings, select which to process, choose vault folders, and write notes.

**CLI surface (overview)**

| Area | Commands |
|------|----------|
| Setup | `meeting-agent init` — vault path, staging root, timezone, auth mode (`token`, `cookie`, `manual_export`, `desktop_session`). |
| Auth | `meeting-agent auth-import` — import Granola desktop session material into the keychain; `meeting-agent auth-check <link>` — verify API access. |
| Processing | `meeting-agent process <link>` — one link; `meeting-agent process-day [--date YYYY-MM-DD]` — discover and batch-select meetings for a day; `process --new` — consume staged/unprocessed transcripts. |
| Convenience | `meeting-agent open --latest` — open the most recently written note from state (macOS `open`). |
| Models | `meeting-agent models pull`, `doctor`, `list` — download and verify local GGUF models and server connectivity. |

Configuration lives at `~/.config/meeting-agent/config.toml`. Staging (transcripts, caches, failed artifacts) uses the `staging_root` you set during `init`.

## Common Command

Run the default daily workflow:

```bash
uv run ma
```

This will:
- discover transcript-ready meetings for today
- let you select meetings (`all` or `1,3-5`)
- prompt `Which folder`
- resolve your folder hint and fall back to `Inbox/` if unmatched
- generate LLM summary and include full transcript by default

Use a custom date:

```bash
uv run ma --date 2026-03-06
```

## Output Modes

`meeting-agent process` supports two output modes:

- default (no flag):
  - Structured note plus a `## Full Transcript` section.
- `--summary`:
  - Summary-only structured note (`Summary`, `Action Items`, `Key Details`, etc.).

Examples:

```bash
uv run meeting-agent process "<granola_link>" --yes --summary
uv run meeting-agent process "<granola_link>" --yes
```

## Single Link Command

Process one known Granola link directly:

```bash
uv run meeting-agent process "<granola_link>" --yes
```
