"""Typer entry point for `balu-code`."""

from __future__ import annotations

import typer

from balu_code_cli import __version__
from balu_code_cli.commands.auth import app as auth_app
from balu_code_cli.commands.chat import app as chat_app
from balu_code_cli.commands.config import app as config_app
from balu_code_cli.commands.index import app as index_app
from balu_code_cli.commands.init import app as init_app
from balu_code_cli.commands.models import app as models_app
from balu_code_cli.commands.session import app as session_app

app = typer.Typer(
    name="balu-code",
    no_args_is_help=True,
    add_completion=False,
    help="Balu Code — self-hosted coding agent.",
)
app.add_typer(auth_app, name="auth")
app.add_typer(init_app, name="init")
app.add_typer(models_app, name="models")
app.add_typer(index_app, name="index")
app.add_typer(chat_app, name="chat")
app.add_typer(session_app, name="session")
app.add_typer(config_app, name="config")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"balu-code {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Balu Code terminal client."""
