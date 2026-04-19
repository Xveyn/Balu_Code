"""Tests for the grep tool."""
from __future__ import annotations

from pathlib import Path

from plugin.services.tools.base import ToolContext
from plugin.services.tools.grep_tool import GrepArgs, GrepTool


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(project_root=tmp_path, project_id=1, turn_id="t_1")


async def test_finds_literal_match(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    return 42\n")
    (tmp_path / "b.py").write_text("def bar():\n    return 0\n")
    t = GrepTool()
    result = await t.execute(GrepArgs(pattern="foo"), _ctx(tmp_path))
    assert result.status == "ok"
    assert "a.py" in result.text
    assert "foo" in result.text
    assert "b.py" not in result.text


async def test_case_insensitive(tmp_path):
    (tmp_path / "a.py").write_text("DEF Foo():\n    pass\n")
    t = GrepTool()
    result = await t.execute(
        GrepArgs(pattern="foo", case_insensitive=True), _ctx(tmp_path)
    )
    assert result.status == "ok"
    assert "a.py" in result.text


async def test_honors_glob_filter(tmp_path):
    (tmp_path / "a.py").write_text("target\n")
    (tmp_path / "b.txt").write_text("target\n")
    t = GrepTool()
    result = await t.execute(
        GrepArgs(pattern="target", glob="*.py"), _ctx(tmp_path)
    )
    assert "a.py" in result.text
    assert "b.txt" not in result.text


async def test_excludes_ignored_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("target\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "leaked.py").write_text("target\n")
    t = GrepTool()
    result = await t.execute(GrepArgs(pattern="target"), _ctx(tmp_path))
    assert "src/a.py" in result.text
    assert ".venv" not in result.text


async def test_zero_matches_returns_empty_text(tmp_path):
    (tmp_path / "a.py").write_text("nothing interesting\n")
    t = GrepTool()
    result = await t.execute(GrepArgs(pattern="xyzzy"), _ctx(tmp_path))
    assert result.status == "ok"
    assert result.text == ""
