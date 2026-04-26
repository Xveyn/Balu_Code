"""init wizard — creates .balucode.yaml in cwd."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console

from balu_code_cli.client.http import BaluCodeHttpClient
from balu_code_cli.config.loader import load_config, load_credentials

app = typer.Typer(help="Initialise a project in the current directory.")
console = Console()


@app.callback(invoke_without_command=True)
def init() -> None:
    """Interactively create a .balucode.yaml for this directory."""
    cfg = load_config()
    creds = load_credentials()

    server_url = cfg.server_url
    if not server_url or server_url not in creds.servers:
        console.print("[red]Not logged in. Run `balu-code auth login` first.[/red]")
        raise typer.Exit(1) from None

    api_key = creds.servers[server_url].api_key
    client = BaluCodeHttpClient(server_url, api_key)

    balucode_path = Path.cwd() / ".balucode.yaml"
    if balucode_path.exists():
        overwrite = typer.confirm(".balucode.yaml already exists. Overwrite?", default=False)
        if not overwrite:
            raise typer.Exit(0)

    # Fetch models for selection
    try:
        models = client.list_models()
    except Exception as exc:
        console.print(f"[red]Could not fetch models: {exc}[/red]")
        raise typer.Exit(1) from None

    name = typer.prompt("Project name")
    root_path = typer.prompt("Root path", default=str(Path.cwd()))

    if models:
        console.print("Available models: " + ", ".join(models))
    model = typer.prompt("Model", default=models[0] if models else "")

    try:
        project = client.create_project(name, root_path)
    except Exception as exc:
        console.print(f"[red]Failed to create project: {exc}[/red]")
        raise typer.Exit(1) from None

    project_id = project["id"]
    data = {
        "project_id": project_id,
        "server_url": server_url,
        "model": model or None,
        "tools": {
            "allow_write": False,
            "allow_bash": False,
            "allow_web_fetch": True,
        },
    }
    balucode_path.write_text(yaml.dump(data))
    console.print(f"[green]Project #{project_id} initialised.[/green] Run `balu-code index` to build the RAG index.")
