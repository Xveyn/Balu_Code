"""chat — interactive REPL with streaming output."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Awaitable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from balu_code_cli.client.ws import BaluCodeWS, connect
from balu_code_cli.config.balucode_yaml import BaluCodeYaml, load_balucode_yaml
from balu_code_cli.config.loader import load_credentials
from balu_code_cli.config.permissions import PermissionsStore, load_permissions
from balu_code_cli.config.paths import permissions_yaml as _permissions_yaml

app = typer.Typer(help="Start an interactive chat session.")
console = Console()

InputFn = Callable[[str], Awaitable[str]]


async def _default_input(prompt: str = "") -> str:
    return await asyncio.to_thread(input, prompt)


def _format_args(args: dict) -> str:
    parts = [f'{k}={repr(v)[:40]}' for k, v in list(args.items())[:3]]
    return ", ".join(parts)


async def _handle_approval(
    ws: BaluCodeWS,
    event: Any,
    balucode: BaluCodeYaml,
    yolo: bool,
    permissions: PermissionsStore,
    perms_path: Path,
    input_fn: InputFn,
) -> None:
    """Resolve an approval_request. Full logic added in Task 12."""
    # Task 11 placeholder: always auto-approve
    await ws.send_approval(event.tool_call_id, approved=True, reason=None)


async def _dispatch_turn(
    ws: BaluCodeWS,
    balucode: BaluCodeYaml,
    yolo: bool,
    permissions: PermissionsStore,
    perms_path: Path,
    input_fn: InputFn,
) -> str | None:
    turn_id = None

    while True:
        event = await ws.receive()

        if event.type == "turn_start":
            turn_id = event.turn_id

        elif event.type == "token":
            print(event.content, end="", flush=True)

        elif event.type == "tool_call":
            label = "(auto)" if event.auto_approved else ""
            print(f"\n🔧 {event.tool}({_format_args(event.args)}) {label}", flush=True)

        elif event.type == "tool_result":
            if event.status == "ok":
                print(f"  ✓ ok ({event.bytes_out} bytes)", flush=True)
            else:
                print(f"  ✗ error: {event.error}", flush=True)

        elif event.type == "approval_request":
            await _handle_approval(ws, event, balucode, yolo, permissions, perms_path, input_fn)

        elif event.type == "turn_end":
            print()
            return turn_id

        elif event.type == "error":
            console.print(f"[red]Error [{event.code}]: {event.message}[/red]")


async def run_chat(
    balucode: BaluCodeYaml,
    api_key: str,
    yolo: bool,
    project_id: int,
    ws_factory=None,
    input_fn: InputFn = _default_input,
    perms_path: Path | None = None,
) -> None:
    _connect = ws_factory or connect
    _perms_path = perms_path or _permissions_yaml()
    permissions = load_permissions(_perms_path)

    async with _connect(balucode.server_url, api_key, project_id) as ws:
        while True:
            try:
                line = await input_fn("[balu-code] > ")
            except (EOFError, KeyboardInterrupt):
                break

            line = line.strip()
            if not line:
                continue
            if line in (".exit", ".quit"):
                break

            await ws.send_message(line)
            turn_id = None
            try:
                turn_id = await _dispatch_turn(ws, balucode, yolo, permissions, _perms_path, input_fn)
            except KeyboardInterrupt:
                if turn_id:
                    await ws.send_cancel(turn_id)
                    console.print("[yellow]Cancelled[/yellow]")


@app.callback(invoke_without_command=True)
def chat(
    yolo: bool = typer.Option(False, "--yolo", help="Auto-approve all tool calls."),
    project_id: int | None = typer.Option(None, "--project-id", help="Override project ID."),
) -> None:
    """Start an interactive chat REPL."""
    try:
        balucode = load_balucode_yaml()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    creds = load_credentials()
    if balucode.server_url not in creds.servers:
        console.print("[red]Not logged in. Run `balu-code auth login` first.[/red]")
        raise typer.Exit(1)

    api_key = creds.servers[balucode.server_url].api_key
    pid = project_id or balucode.project_id

    asyncio.run(run_chat(balucode=balucode, api_key=api_key, yolo=yolo, project_id=pid))
