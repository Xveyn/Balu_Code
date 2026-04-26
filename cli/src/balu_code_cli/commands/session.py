"""session list / resume / delete commands."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from balu_code_cli.commands.chat import run_chat
from balu_code_cli.config.balucode_yaml import load_balucode_yaml
from balu_code_cli.config.loader import load_credentials
from balu_code_cli.config.paths import sessions_dir
from balu_code_cli.session.reader import SessionReader

app = typer.Typer(help="Manage chat sessions.")
console = Console()


def _find_session(sess_dir: Path, id_prefix: str) -> Path:
    def _uuid_part(f: Path) -> str:
        parts = f.stem.split("_", 2)
        return parts[2] if len(parts) >= 3 else f.stem

    matches = [f for f in sess_dir.glob("*.jsonl") if _uuid_part(f).startswith(id_prefix)]
    if not matches:
        console.print(f"[red]No session matches prefix '{id_prefix}'[/red]")
        raise typer.Exit(1)
    if len(matches) > 1:
        names = ", ".join(f.name for f in matches)
        console.print(f"[red]Ambiguous prefix — matches: {names}[/red]")
        raise typer.Exit(1)
    return matches[0]


@app.command("list")
def session_list() -> None:
    """List sessions for the current project."""
    try:
        balucode = load_balucode_yaml()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None

    sess_dir = sessions_dir(balucode.server_url, balucode.project_id)
    if not sess_dir.exists():
        console.print("No sessions yet.")
        return

    files = sorted(sess_dir.glob("*.jsonl"), reverse=True)
    if not files:
        console.print("No sessions yet.")
        return

    table = Table(title="Sessions")
    table.add_column("Timestamp")
    table.add_column("Turns", justify="right")
    table.add_column("ID (prefix)")

    for f in files:
        reader = SessionReader(f)
        meta = reader.metadata()
        ts_raw = meta["start_ts"]
        ts = ts_raw[:16].replace("T", " ") if ts_raw else "?"
        # filename: <ts>_<user>_<uuid>.jsonl — split on "_" max 2 times
        parts = f.stem.split("_", 2)
        uid_prefix = parts[2][:8] if len(parts) >= 3 else f.stem[:8]
        table.add_row(ts, str(meta["turn_count"]), uid_prefix)

    console.print(table)


@app.command("resume")
def session_resume(
    id_prefix: str = typer.Argument(..., help="UUID prefix of the session to resume."),
) -> None:
    """Resume a previous chat session."""
    try:
        balucode = load_balucode_yaml()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None

    sess_dir = sessions_dir(balucode.server_url, balucode.project_id)
    session_path = _find_session(sess_dir, id_prefix)
    initial_messages = SessionReader(session_path).messages()

    creds = load_credentials()
    if balucode.server_url not in creds.servers:
        console.print("[red]Not logged in. Run `balu-code auth login` first.[/red]")
        raise typer.Exit(1)

    api_key = creds.servers[balucode.server_url].api_key
    asyncio.run(
        run_chat(
            balucode=balucode,
            api_key=api_key,
            yolo=False,
            project_id=balucode.project_id,
            initial_messages=initial_messages,
        )
    )


@app.command("delete")
def session_delete(
    id_prefix: str = typer.Argument(..., help="UUID prefix of the session to delete."),
) -> None:
    """Delete a session."""
    try:
        balucode = load_balucode_yaml()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None

    sess_dir = sessions_dir(balucode.server_url, balucode.project_id)
    session_path = _find_session(sess_dir, id_prefix)

    confirmed = typer.confirm(f"Really delete {session_path.name}?", default=False)
    if confirmed:
        session_path.unlink()
        console.print("[green]Deleted.[/green]")
    else:
        console.print("Aborted.")
