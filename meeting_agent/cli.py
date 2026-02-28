import typer

app = typer.Typer(help="Meeting Agent CLI")


@app.callback(invoke_without_command=True)
def main() -> None:
    """Entry point placeholder for the meeting-agent CLI."""
    return
