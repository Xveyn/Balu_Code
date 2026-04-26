"""Tests for write_file tool."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from plugin.services.cancel import CancelToken
from plugin.services.tools.base import ToolContext
from plugin.services.tools.write_file import WriteFileArgs, WriteFileTool


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        project_root=tmp_path,
        project_id=1,
        turn_id="t_test",
        cancel_token=CancelToken(),
    )


@pytest.mark.asyncio
async def test_creates_new_file(ctx: ToolContext) -> None:
    tool = WriteFileTool()
    result = await tool.execute(
        WriteFileArgs(path="foo.py", content="print('hi')\n"),
        ctx,
    )
    assert result.status == "ok"
    assert (ctx.project_root / "foo.py").read_text() == "print('hi')\n"
    assert "wrote" in result.text.lower()
    assert result.bytes_out == len(b"print('hi')\n")


@pytest.mark.asyncio
async def test_overwrites_existing_file(ctx: ToolContext) -> None:
    (ctx.project_root / "foo.py").write_text("old\n")
    tool = WriteFileTool()
    result = await tool.execute(
        WriteFileArgs(path="foo.py", content="new\n"),
        ctx,
    )
    assert result.status == "ok"
    assert (ctx.project_root / "foo.py").read_text() == "new\n"


@pytest.mark.asyncio
async def test_rejects_missing_parent_without_create_dirs(ctx: ToolContext) -> None:
    tool = WriteFileTool()
    result = await tool.execute(
        WriteFileArgs(path="new/sub/foo.py", content="x"),
        ctx,
    )
    assert result.status == "error"
    assert "parent" in result.error.lower() or "directory" in result.error.lower()


@pytest.mark.asyncio
async def test_create_dirs_true_builds_missing_parents(ctx: ToolContext) -> None:
    tool = WriteFileTool()
    result = await tool.execute(
        WriteFileArgs(path="new/sub/foo.py", content="x", create_dirs=True),
        ctx,
    )
    assert result.status == "ok"
    assert (ctx.project_root / "new" / "sub" / "foo.py").read_text() == "x"


@pytest.mark.asyncio
async def test_rejects_path_traversal(ctx: ToolContext) -> None:
    tool = WriteFileTool()
    result = await tool.execute(
        WriteFileArgs(path="../escape.py", content="x"),
        ctx,
    )
    assert result.status == "error"
    assert "escape" in result.error.lower()


def test_rejects_content_over_size_cap() -> None:
    big = "x" * (2 * 1024 * 1024 + 1)  # 2 MB + 1 byte
    with pytest.raises(ValidationError):
        WriteFileArgs(path="big.txt", content=big)


@pytest.mark.asyncio
async def test_accepts_utf8_content(ctx: ToolContext) -> None:
    tool = WriteFileTool()
    result = await tool.execute(
        WriteFileArgs(path="umlaute.txt", content="Grüße, 你好"),
        ctx,
    )
    assert result.status == "ok"
    assert (ctx.project_root / "umlaute.txt").read_text(encoding="utf-8") == "Grüße, 你好"


@pytest.mark.asyncio
async def test_preserves_exact_bytes_no_line_ending_magic(ctx: ToolContext) -> None:
    tool = WriteFileTool()
    content = "line1\r\nline2\nline3\r"
    result = await tool.execute(
        WriteFileArgs(path="crlf.txt", content=content),
        ctx,
    )
    assert result.status == "ok"
    assert (ctx.project_root / "crlf.txt").read_bytes() == content.encode("utf-8")


def test_risk_is_write() -> None:
    assert WriteFileTool.risk == "write"
