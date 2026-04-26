"""Tests for apply_patch tool."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from plugin.services.cancel import CancelToken
from plugin.services.tools.apply_patch import ApplyPatchArgs, ApplyPatchTool
from plugin.services.tools.base import ToolContext


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        project_root=tmp_path,
        project_id=1,
        turn_id="t_test",
        cancel_token=CancelToken(),
    )


@pytest.mark.asyncio
async def test_single_hunk_modification(ctx: ToolContext) -> None:
    target = ctx.project_root / "foo.txt"
    target.write_text("line1\nline2\nline3\n")
    diff = """--- a/foo.txt
+++ b/foo.txt
@@ -1,3 +1,3 @@
 line1
-line2
+LINE TWO
 line3
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "ok"
    assert target.read_text() == "line1\nLINE TWO\nline3\n"
    assert "hunk" in result.text.lower()


@pytest.mark.asyncio
async def test_multi_file_patch(ctx: ToolContext) -> None:
    a = ctx.project_root / "a.txt"
    b = ctx.project_root / "b.txt"
    a.write_text("A1\n")
    b.write_text("B1\n")
    diff = """--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-A1
+A2
--- a/b.txt
+++ b/b.txt
@@ -1 +1 @@
-B1
+B2
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "ok"
    assert a.read_text() == "A2\n"
    assert b.read_text() == "B2\n"


@pytest.mark.asyncio
async def test_creates_file_from_dev_null(ctx: ToolContext) -> None:
    diff = """--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+hello
+world
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "ok"
    assert (ctx.project_root / "new.txt").read_text() == "hello\nworld\n"


@pytest.mark.asyncio
async def test_deletes_file_to_dev_null(ctx: ToolContext) -> None:
    target = ctx.project_root / "gone.txt"
    target.write_text("bye\n")
    diff = """--- a/gone.txt
+++ /dev/null
@@ -1 +0,0 @@
-bye
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "ok"
    assert not target.exists()


@pytest.mark.asyncio
async def test_fails_fast_on_context_mismatch(ctx: ToolContext) -> None:
    target = ctx.project_root / "foo.txt"
    target.write_text("NOT the expected content\n")
    diff = """--- a/foo.txt
+++ b/foo.txt
@@ -1 +1 @@
-line1
+LINE ONE
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "error"
    assert target.read_text() == "NOT the expected content\n"


@pytest.mark.asyncio
async def test_multi_file_mismatch_leaves_all_untouched(ctx: ToolContext) -> None:
    a = ctx.project_root / "a.txt"
    b = ctx.project_root / "b.txt"
    a.write_text("A1\n")
    b.write_text("WRONG\n")
    diff = """--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-A1
+A2
--- a/b.txt
+++ b/b.txt
@@ -1 +1 @@
-B1
+B2
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "error"
    assert a.read_text() == "A1\n"
    assert b.read_text() == "WRONG\n"


@pytest.mark.asyncio
async def test_rejects_path_traversal(ctx: ToolContext) -> None:
    diff = """--- a/../escape.txt
+++ b/../escape.txt
@@ -0,0 +1 @@
+x
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "error"
    assert "escape" in result.error.lower()


@pytest.mark.asyncio
async def test_rejects_empty_diff() -> None:
    with pytest.raises(ValidationError):
        ApplyPatchArgs(diff="")


def test_risk_is_write() -> None:
    assert ApplyPatchTool.risk == "write"
