"""Tests for Tool Protocol + ToolRegistry."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from plugin.services.cancel import CancelToken
from plugin.services.tools import ToolRegistry
from plugin.services.tools.base import ToolContext, ToolResult


class _EchoArgs(BaseModel):
    message: str


class _EchoTool:
    name = "echo"
    description = "Echo the message back."
    args_schema = _EchoArgs
    risk = "read"

    async def execute(self, args: _EchoArgs, ctx: ToolContext) -> ToolResult:
        return ToolResult(status="ok", text=args.message, bytes_out=len(args.message))


def test_register_and_get_tool():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    t = reg.get("echo")
    assert t.name == "echo"


def test_get_unknown_tool_raises_key_error():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.get("does_not_exist")


def test_register_duplicate_raises():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    with pytest.raises(ValueError):
        reg.register(_EchoTool())


def test_names_returns_registered_tool_names():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    assert reg.names() == ["echo"]


def test_ollama_schemas_shape():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    schemas = reg.ollama_schemas()
    assert len(schemas) == 1
    s = schemas[0]
    assert s["type"] == "function"
    assert s["function"]["name"] == "echo"
    assert s["function"]["description"] == "Echo the message back."
    params = s["function"]["parameters"]
    assert params["type"] == "object"
    assert "message" in params["properties"]
    assert params["properties"]["message"]["type"] == "string"


async def test_tool_execute_returns_tool_result():
    t = _EchoTool()
    ctx = ToolContext(
        project_root=Path("/tmp"), project_id=1, turn_id="t_1", cancel_token=CancelToken()
    )
    result = await t.execute(_EchoArgs(message="hi"), ctx)
    assert isinstance(result, ToolResult)
    assert result.status == "ok"
    assert result.text == "hi"
    assert result.bytes_out == 2


def test_default_registry_includes_all_seven_tools():
    from plugin.services.tools import default_registry

    reg = default_registry()
    assert set(reg.names()) == {
        "read_file",
        "glob",
        "grep",
        "write_file",
        "apply_patch",
        "run_bash",
        "web_fetch",
    }
