"""Tests for the read_file tool."""

from __future__ import annotations

from pathlib import Path

from plugin.services.tools.base import ToolContext
from plugin.services.tools.read_file import ReadFileArgs, ReadFileTool


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(project_root=tmp_path, project_id=1, turn_id="t_1")


async def test_reads_utf8_file(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    t = ReadFileTool()
    result = await t.execute(ReadFileArgs(path="a.py"), _ctx(tmp_path))
    assert result.status == "ok"
    assert "def foo" in result.text
    assert result.bytes_out > 0


async def test_rejects_path_escape(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    t = ReadFileTool()
    result = await t.execute(ReadFileArgs(path="../escape.txt"), _ctx(tmp_path))
    assert result.status == "error"
    assert "escape" in (result.error or "").lower() or "root" in (result.error or "").lower()


async def test_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    try:
        link = tmp_path / "link.txt"
        link.symlink_to(outside)
        t = ReadFileTool()
        result = await t.execute(ReadFileArgs(path="link.txt"), _ctx(tmp_path))
        assert result.status == "error"
    finally:
        if outside.exists():
            outside.unlink()


async def test_rejects_binary_file(tmp_path):
    (tmp_path / "img.bin").write_bytes(b"\x00\x01\x02\x03\x04")
    t = ReadFileTool()
    result = await t.execute(ReadFileArgs(path="img.bin"), _ctx(tmp_path))
    assert result.status == "error"
    assert "binary" in (result.error or "").lower()


async def test_returns_error_for_missing_file(tmp_path):
    t = ReadFileTool()
    result = await t.execute(ReadFileArgs(path="nope.py"), _ctx(tmp_path))
    assert result.status == "error"


async def test_truncates_at_max_bytes(tmp_path):
    (tmp_path / "big.py").write_text("x" * 10_000)
    t = ReadFileTool()
    result = await t.execute(ReadFileArgs(path="big.py", max_bytes=100), _ctx(tmp_path))
    assert result.status == "ok"
    assert len(result.text.encode("utf-8", errors="replace")) <= 100
