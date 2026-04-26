"""index — start indexing and poll until done."""

from __future__ import annotations

import time

import typer
from rich.console import Console

from balu_code_cli.client.http import BaluCodeHttpClient
from balu_code_cli.config.balucode_yaml import load_balucode_yaml
from balu_code_cli.config.loader import load_credentials

app = typer.Typer(help="Index the current project.")
console = Console()
_POLL_INTERVAL = 2  # seconds


@app.callback(invoke_without_command=True)
def index() -> None:
    """Start indexing the current project and wait for completion."""
    try:
        balucode = load_balucode_yaml()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    creds = load_credentials()
    if balucode.server_url not in creds.servers:
        console.print("[red]Not logged in. Run `balu-code auth login` first.[/red]")
        raise typer.Exit(1)

    client = BaluCodeHttpClient(balucode.server_url, creds.servers[balucode.server_url].api_key)

    try:
        job = client.start_index(balucode.project_id)
    except Exception as exc:
        console.print(f"[red]Failed to start index: {exc}[/red]")
        raise typer.Exit(1)

    job_id = job["job_id"]
    with console.status("[bold green]Indexing…"):
        while True:
            try:
                status = client.index_status(balucode.project_id, job_id)
            except Exception as exc:
                console.print(f"[red]Error polling status: {exc}[/red]")
                raise typer.Exit(1)

            if status["status"] == "done":
                console.print(
                    f"[green]Done.[/green] "
                    f"{status['files_processed']}/{status['files_total']} files, "
                    f"{status['chunks_total']} chunks."
                )
                return
            if status["status"] == "failed":
                console.print(f"[red]Indexing failed: {status.get('error')}[/red]")
                raise typer.Exit(1)
            if status["status"] not in ("running", "pending"):
                console.print(f"[red]Unexpected index status: {status['status']}[/red]")
                raise typer.Exit(1)

            time.sleep(_POLL_INTERVAL)
