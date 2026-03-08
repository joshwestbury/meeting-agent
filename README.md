# Meeting Agent

Local CLI for turning Granola meeting transcripts into structured Obsidian notes.

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
