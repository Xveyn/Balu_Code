"""models — list available Ollama models."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from balu_code_cli.client.http import BaluCodeHttpClient
from balu_code_cli.config.loader import load_config, load_credentials

app = typer.Typer(help="List available models.")
console = Console()


@app.callback(invoke_without_command=True)
def models() -> None:
    """List models available on the configured server."""
    cfg = load_config()
    creds = load_credentials()
    if not cfg.server_url or cfg.server_url not in creds.servers:
        console.print("[red]Not logged in. Run `balu-code auth login` first.[/red]")
        raise typer.Exit(1) from None

    client = BaluCodeHttpClient(cfg.server_url, creds.servers[cfg.server_url].api_key)
    try:
        names = client.list_models()
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from None

    table = Table(title="Available Models")
    table.add_column("Name")
    for name in names:
        table.add_row(name)
    console.print(table)
