import typer

from meeting_agent.config import (
    AppConfig,
    load_and_validate_startup_config,
    save_config,
    validate_init_config,
)
from meeting_agent.errors import ConfigError

app = typer.Typer(help="Meeting Agent CLI")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Entry point for meeting-agent CLI."""
    if ctx.invoked_subcommand == "init":
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
        "Auth mode (token/cookie/manual_export)",
        default="manual_export",
    )
    auth_mode = auth_mode.strip()
    if auth_mode not in {"token", "cookie", "manual_export"}:
        typer.echo("Auth mode must be one of: token, cookie, manual_export")
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
