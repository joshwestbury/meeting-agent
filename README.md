# Meeting Agent

Local CLI for turning Granola meeting transcripts into structured Obsidian notes.

## Common Command

Process one Granola link and write a note:

```bash
uv run meeting-agent process "<granola_link>" --yes
```

- This uses the local model (if configured and running).
- It writes the note into your configured `vault_root` and folder.

## Output Modes

`meeting-agent process` supports two output modes:

- `--summary`:
  - Summary-style note (default behavior).
  - Includes structured sections (`Summary`, `Action Items`, `Key Details`, etc.).
- `--full`:
  - Same structured note, plus a `## Full Transcript` section containing the entire transcript text.

Examples:

```bash
uv run meeting-agent process "<granola_link>" --yes --summary
uv run meeting-agent process "<granola_link>" --yes --full
```

## Shell Shortcut (`ma`)

If you want a shorter command, add this function to your `~/.zshrc`:

```zsh
ma() {
  uv run meeting-agent process "$1" --yes "${@:2}"
}
```

Reload shell config:

```zsh
source ~/.zshrc
```

Verify it is loaded:

```zsh
type ma
```

Expected output includes: `ma is a shell function`.

Then use:

```bash
ma "<granola_link>" --summary
ma "<granola_link>" --full
```

Notes:
- `--summary` is optional because summary is default.
- Prefer `ma` (no leading `-`) for reliable zsh behavior.
