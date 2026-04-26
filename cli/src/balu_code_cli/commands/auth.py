"""auth login + auth status commands."""

from __future__ import annotations

import sys

import httpx
import typer
from rich.console import Console
from rich.table import Table

from balu_code_cli.client.http import BaluCodeHttpClient
from balu_code_cli.config.loader import (
    AppConfig,
    Credentials,
    ServerCredentials,
    load_config,
    load_credentials,
    save_config,
    save_credentials,
)

app = typer.Typer(help="Manage authentication.")
console = Console()


@app.command("login")
def login() -> None:
    """Authenticate with a BaluHost server using an API key."""
    cfg = load_config()
    server_url = typer.prompt("Server URL", default=cfg.server_url or "")
    api_key = typer.prompt("API key", hide_input=True)

    try:
        BaluCodeHttpClient(server_url, api_key).health()
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]Authentication failed (HTTP {exc.response.status_code}). Check your API key.[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]Could not reach server: {exc}[/red]")
        raise typer.Exit(1)

    creds = load_credentials()
    creds.servers[server_url] = ServerCredentials(api_key=api_key)
    save_credentials(creds)

    cfg.server_url = server_url
    save_config(cfg)

    console.print(f"[green]Logged in to {server_url}[/green]")


@app.command("status")
def status() -> None:
    """Show current authentication status."""
    cfg = load_config()
    creds = load_credentials()

    if not cfg.server_url or cfg.server_url not in creds.servers:
        console.print("[yellow]Not logged in. Run `balu-code auth login`.[/yellow]")
        raise typer.Exit(1)

    server_url = cfg.server_url
    api_key = creds.servers[server_url].api_key

    try:
        BaluCodeHttpClient(server_url, api_key).health()
        ok = "✓ ok"
    except Exception:
        ok = "✗ unreachable"

    table = Table(title="Auth Status")
    table.add_column("Server")
    table.add_column("API Key")
    table.add_column("Status")
    table.add_row(server_url, api_key[:8] + "...", ok)
    console.print(table)
