"""Tests for commands/chat.py."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from balu_code_cli.client.ws import BaluCodeWS
from balu_code_cli.commands.chat import run_chat
from balu_code_cli.config.balucode_yaml import BaluCodeYaml
from typer.testing import CliRunner

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


@pytest.mark.asyncio
async def test_yolo_auto_approves(capsys):
    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "approval_request", "tool_call_id": "tc_1",
         "tool": "write_file", "args": {"path": "x.py"}, "risk": "write"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 5, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    inputs = asyncio.Queue()
    await inputs.put("go")
    await inputs.put(EOFError())

    async def fake_input(_p=""):
        item = await inputs.get()
        if isinstance(item, BaseException):
            raise item
        return item

    await run_chat(
        balucode=_BALUCODE, api_key="key", yolo=True,
        project_id=1, ws_factory=_make_ws_factory(ws), input_fn=fake_input,
    )
    ws.send_approval.assert_called_once_with("tc_1", approved=True, reason=None)


@pytest.mark.asyncio
async def test_balucode_allow_auto_approves(capsys):
    from balu_code_cli.config.balucode_yaml import ToolsConfig
    balucode = BaluCodeYaml(project_id=1, server_url="https://x.com",
                            tools=ToolsConfig(allow_write=True))
    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "approval_request", "tool_call_id": "tc_2",
         "tool": "write_file", "args": {}, "risk": "write"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 5, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    inputs = asyncio.Queue()
    await inputs.put("go")
    await inputs.put(EOFError())

    async def fake_input(_p=""):
        item = await inputs.get()
        if isinstance(item, BaseException):
            raise item
        return item

    await run_chat(
        balucode=balucode, api_key="key", yolo=False,
        project_id=1, ws_factory=_make_ws_factory(ws), input_fn=fake_input,
    )
    ws.send_approval.assert_called_once_with("tc_2", approved=True, reason=None)


@pytest.mark.asyncio
async def test_stored_yes_auto_approves(tmp_path):
    from balu_code_cli.config.permissions import PermissionsStore, save_permissions
    store = PermissionsStore()
    store.set("https://x.com", 1, "run_bash", True)
    perms_path = tmp_path / "perms.yaml"
    save_permissions(store, perms_path)

    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "approval_request", "tool_call_id": "tc_3",
         "tool": "run_bash", "args": {"command": "ls"}, "risk": "exec"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 5, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    balucode = BaluCodeYaml(project_id=1, server_url="https://x.com")
    inputs = asyncio.Queue()
    await inputs.put("go")
    await inputs.put(EOFError())

    async def fake_input(_p=""):
        item = await inputs.get()
        if isinstance(item, BaseException):
            raise item
        return item

    await run_chat(
        balucode=balucode, api_key="key", yolo=False, project_id=1,
        ws_factory=_make_ws_factory(ws), input_fn=fake_input,
        perms_path=perms_path,
    )
    ws.send_approval.assert_called_once_with("tc_3", approved=True, reason=None)


@pytest.mark.asyncio
async def test_interactive_y_approves_once(tmp_path):
    from balu_code_cli.config.permissions import load_permissions
    perms_path = tmp_path / "perms.yaml"

    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "approval_request", "tool_call_id": "tc_4",
         "tool": "write_file", "args": {"path": "a.py"}, "risk": "write"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 5, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    balucode = BaluCodeYaml(project_id=1, server_url="https://x.com")

    user_inputs = asyncio.Queue()
    await user_inputs.put("go")         # REPL prompt
    await user_inputs.put("y")          # approval prompt
    await user_inputs.put(EOFError())   # exit REPL

    async def fake_input(_p=""):
        item = await user_inputs.get()
        if isinstance(item, BaseException):
            raise item
        return item

    await run_chat(
        balucode=balucode, api_key="key", yolo=False, project_id=1,
        ws_factory=_make_ws_factory(ws), input_fn=fake_input,
        perms_path=perms_path,
    )
    ws.send_approval.assert_called_once_with("tc_4", approved=True, reason=None)
    # "y" (not "Y") → not persisted
    store = load_permissions(perms_path)
    assert store.lookup("https://x.com", 1, "write_file") is None


@pytest.mark.asyncio
async def test_interactive_Y_approves_always(tmp_path):
    from balu_code_cli.config.permissions import load_permissions
    perms_path = tmp_path / "perms.yaml"

    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "approval_request", "tool_call_id": "tc_5",
         "tool": "write_file", "args": {}, "risk": "write"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 5, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    balucode = BaluCodeYaml(project_id=1, server_url="https://x.com")

    user_inputs = asyncio.Queue()
    await user_inputs.put("go")
    await user_inputs.put("Y")   # always
    await user_inputs.put(EOFError())

    async def fake_input(_p=""):
        item = await user_inputs.get()
        if isinstance(item, BaseException):
            raise item
        return item

    await run_chat(
        balucode=balucode, api_key="key", yolo=False, project_id=1,
        ws_factory=_make_ws_factory(ws), input_fn=fake_input,
        perms_path=perms_path,
    )
    ws.send_approval.assert_called_once_with("tc_5", approved=True, reason=None)
    store = load_permissions(perms_path)
    assert store.lookup("https://x.com", 1, "write_file") is True


@pytest.mark.asyncio
async def test_stored_no_auto_denies(tmp_path):
    from balu_code_cli.config.permissions import PermissionsStore, save_permissions

    store = PermissionsStore()
    store.set("https://x.com", 1, "run_bash", False)
    perms_path = tmp_path / "perms.yaml"
    save_permissions(store, perms_path)

    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "approval_request", "tool_call_id": "tc_6",
         "tool": "run_bash", "args": {"command": "rm -rf /"}, "risk": "exec"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 5, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    balucode = BaluCodeYaml(project_id=1, server_url="https://x.com")

    approval_prompt_calls: list[str] = []
    inputs = asyncio.Queue()
    await inputs.put("go")
    await inputs.put(EOFError())

    async def fake_input(_p=""):
        # The REPL prompts with "[balu-code] > "; approval prompts contain "Allow?"
        if "Allow?" in _p:
            approval_prompt_calls.append(_p)
            raise AssertionError("input_fn should not be called for approval when stored=False")
        item = await inputs.get()
        if isinstance(item, BaseException):
            raise item
        return item

    await run_chat(
        balucode=balucode, api_key="key", yolo=False, project_id=1,
        ws_factory=_make_ws_factory(ws), input_fn=fake_input,
        perms_path=perms_path,
    )
    assert approval_prompt_calls == [], "input_fn was called for approval despite stored=False"
    ws.send_approval.assert_called_once_with("tc_6", approved=False, reason=None)


@pytest.mark.asyncio
async def test_interactive_N_denies_always(tmp_path):
    from balu_code_cli.config.permissions import load_permissions
    perms_path = tmp_path / "perms.yaml"

    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "approval_request", "tool_call_id": "tc_7",
         "tool": "write_file", "args": {"path": "b.py"}, "risk": "write"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 5, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    balucode = BaluCodeYaml(project_id=1, server_url="https://x.com")

    user_inputs = asyncio.Queue()
    await user_inputs.put("go")
    await user_inputs.put("N")   # deny always
    await user_inputs.put(EOFError())

    async def fake_input(_p=""):
        item = await user_inputs.get()
        if isinstance(item, BaseException):
            raise item
        return item

    await run_chat(
        balucode=balucode, api_key="key", yolo=False, project_id=1,
        ws_factory=_make_ws_factory(ws), input_fn=fake_input,
        perms_path=perms_path,
    )
    ws.send_approval.assert_called_once_with("tc_7", approved=False, reason=None)
    store = load_permissions(perms_path)
    assert store.lookup("https://x.com", 1, "write_file") is False
