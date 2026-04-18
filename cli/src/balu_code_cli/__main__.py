"""Typer entry point for `balu-code`.

Phase 1 only registers the top-level ``--version`` callback. Real
subcommands (auth, init, chat, …) land in later phases.
"""

from __future__ import annotations

import typer

from balu_code_cli import __version__

app = typer.Typer(
    name="balu-code",
    no_args_is_help=True,
    add_completion=False,
    help="Balu Code — self-hosted coding agent.",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"balu-code {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Balu Code terminal client."""
