"""Tests for commands/chat.py."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from balu_code_cli.__main__ import app
from balu_code_cli.client.ws import BaluCodeWS
from balu_code_cli.commands.chat import run_chat
from balu_code_cli.config.balucode_yaml import BaluCodeYaml

runner = CliRunner()
_BALUCODE = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")


def _make_fake_ws(events: list[dict]) -> BaluCodeWS:
    """Return a BaluCodeWS that replays the given frames."""
    from balu_code_shared.events import parse_frame
    ws = MagicMock(spec=BaluCodeWS)
    frames = [parse_frame(e) for e in events]
    call_count = [0]

    async def recv():
        ev = frames[call_count[0]]
        call_count[0] += 1
        return ev

    ws.receive = recv
    ws.send_message = AsyncMock()
    ws.send_approval = AsyncMock()
    ws.send_cancel = AsyncMock()
    return ws


def _make_ws_factory(ws):
    @asynccontextmanager
    async def factory(server_url, api_key, project_id) -> AsyncIterator[BaluCodeWS]:
        yield ws
    return factory


@pytest.mark.asyncio
async def test_run_chat_streams_tokens(capsys):
    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 10},
        {"type": "token", "content": "Hello"},
        {"type": "token", "content": " world"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 15, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)

    # Simulate one user message then EOF
    inputs = asyncio.Queue()
    await inputs.put("write a function")
    await inputs.put(EOFError())

    async def fake_input(_prompt=""):
        item = await inputs.get()
        if isinstance(item, BaseException):
            raise item
        return item

    await run_chat(
        balucode=_BALUCODE,
        api_key="key",
        yolo=False,
        project_id=1,
        ws_factory=_make_ws_factory(ws),
        input_fn=fake_input,
    )

    captured = capsys.readouterr()
    assert "Hello" in captured.out
    assert " world" in captured.out


@pytest.mark.asyncio
async def test_run_chat_displays_tool_call(capsys):
    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "tool_call", "tool_call_id": "tc_1", "tool": "read_file",
         "args": {"path": "foo.py"}, "auto_approved": True},
        {"type": "tool_result", "tool_call_id": "tc_1", "status": "ok", "bytes_out": 42, "error": None},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 10, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    inputs = asyncio.Queue()
    await inputs.put("read foo")
    await inputs.put(EOFError())

    async def fake_input(_prompt=""):
        item = await inputs.get()
        if isinstance(item, BaseException):
            raise item
        return item

    await run_chat(
        balucode=_BALUCODE,
        api_key="key",
        yolo=False,
        project_id=1,
        ws_factory=_make_ws_factory(ws),
        input_fn=fake_input,
    )
    captured = capsys.readouterr()
    assert "read_file" in captured.out
