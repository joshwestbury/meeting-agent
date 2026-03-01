from pathlib import Path

import typer

from meeting_agent.config import (
    AppConfig,
    load_and_validate_startup_config,
    save_config,
    validate_init_config,
)
from meeting_agent.errors import ConfigError, RetrievalError
from meeting_agent.auth import import_desktop_session_credentials
from meeting_agent.retrieval import retrieve_transcript

app = typer.Typer(help="Meeting Agent CLI")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Entry point for meeting-agent CLI."""
    if ctx.invoked_subcommand in {"init", "auth-import"}:
        return

    try:
        load_and_validate_startup_config()
    except ConfigError as exc:
        typer.echo(
            f"Configuration error: {exc}\nRun `meeting-agent init` to create/update config."
        )
        raise typer.Exit(code=2) from exc

    if ctx.invoked_subcommand is None:
        typer.echo("Interactive flow is not implemented yet. Use `meeting-agent init` first.")


@app.command("init")
def init_command() -> None:
    """Initialize meeting-agent configuration."""
    default_vault_root = "~/Documents/Alter Mentis Obsidian Vault"
    default_staging_root = "~/granola-export"
    default_timezone = "local"

    vault_root = typer.prompt("Vault root", default=default_vault_root)
    staging_root = typer.prompt("Staging root", default=default_staging_root)
    default_folder_raw = typer.prompt("Default vault-relative folder", default="", show_default=False)
    timezone = typer.prompt("Timezone", default=default_timezone)
    auth_mode = typer.prompt(
        "Auth mode (token/cookie/manual_export/desktop_session)",
        default="manual_export",
    )
    auth_mode = auth_mode.strip()
    if auth_mode not in {"token", "cookie", "manual_export", "desktop_session"}:
        typer.echo("Auth mode must be one of: token, cookie, manual_export, desktop_session")
        raise typer.Exit(code=2)

    auth_token_env: str | None = None
    cookie_file: str | None = None
    if auth_mode == "token":
        auth_token_env = typer.prompt("Token environment variable name", default="MEETING_AGENT_TOKEN")
    elif auth_mode == "cookie":
        cookie_file = typer.prompt(
            "Cookie file path",
            default="~/.config/meeting-agent/cookies.txt",
        )

    config = AppConfig(
        vault_root=vault_root,
        staging_root=staging_root,
        default_folder=default_folder_raw or None,
        timezone=timezone,
        auth_mode=auth_mode,
        auth_token_env=auth_token_env,
        cookie_file=cookie_file,
    )

    try:
        validate_init_config(config)
    except ConfigError as exc:
        typer.echo(f"Config validation failed: {exc}")
        raise typer.Exit(code=2) from exc

    path = save_config(config)
    typer.echo(f"Config written: {path}")
    typer.echo("Startup validation passed.")


@app.command("auth-import")
def auth_import_command(
    session_path: str | None = typer.Option(
        None,
        "--session-path",
        help="Path to Granola desktop session credential file.",
    )
) -> None:
    """Import Granola desktop-session credentials into keychain storage."""
    source_path = Path(session_path).expanduser() if session_path else None
    creds = import_desktop_session_credentials(source_path)
    typer.echo("Desktop-session credentials imported.")
    typer.echo(f"client_id: {creds.client_id}")
    typer.echo(f"has_access_token: {bool(creds.access_token)}")


@app.command("auth-check")
def auth_check_command(granola_link: str) -> None:
    """Validate real Granola connectivity/auth using a meeting link."""
    config = load_and_validate_startup_config()
    if config.auth_mode == "manual_export":
        typer.echo(
            "auth-check requires remote auth mode (`token` or `cookie`). "
            "Current config is `manual_export`."
        )
        raise typer.Exit(code=2)

    typer.echo("Checking Granola connectivity...")
    try:
        result = retrieve_transcript(granola_link, config, max_retries=0)
    except RetrievalError as exc:
        typer.echo(f"Granola auth-check failed [{exc.code}]: {exc}")
        raise typer.Exit(code=2) from exc

    typer.echo("Granola auth-check succeeded.")
    typer.echo(f"meeting_id: {result.meeting_id}")
    typer.echo(f"transcript_chars: {len(result.transcript_text)}")
