"""config get / set commands."""

from __future__ import annotations

import typer
from rich.console import Console

from balu_code_cli.config.loader import load_config, save_config

app = typer.Typer(help="Get or set CLI configuration values.")
console = Console()

_VALID_KEYS = frozenset({"server_url", "default_project_id"})


@app.command("get")
def config_get(key: str = typer.Argument(..., help="Config key to read.")) -> None:
    """Print the current value of a config key."""
    if key not in _VALID_KEYS:
        console.print(
            f"[red]Unknown key '{key}'. Valid keys: {', '.join(sorted(_VALID_KEYS))}[/red]"
        )
        raise typer.Exit(1)
    cfg = load_config()
    value = getattr(cfg, key)
    typer.echo("" if value is None else str(value))


@app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key to update."),
    value: str = typer.Argument(..., help="New value."),
) -> None:
    """Set a config key to a new value."""
    if key not in _VALID_KEYS:
        console.print(
            f"[red]Unknown key '{key}'. Valid keys: {', '.join(sorted(_VALID_KEYS))}[/red]"
        )
        raise typer.Exit(1)

    cfg = load_config()
    if key == "default_project_id":
        try:
            setattr(cfg, key, int(value))
        except ValueError:
            console.print(f"[red]Expected integer for {key}[/red]")
            raise typer.Exit(1) from None
    else:
        setattr(cfg, key, value)

    save_config(cfg)
    console.print(f"[green]{key} = {value}[/green]")
