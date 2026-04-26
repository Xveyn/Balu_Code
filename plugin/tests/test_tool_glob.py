"""Tests for the glob tool."""

from __future__ import annotations

from pathlib import Path

from plugin.services.cancel import CancelToken
from plugin.services.tools.base import ToolContext
from plugin.services.tools.glob_tool import GlobArgs, GlobTool


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        project_root=tmp_path, project_id=1, turn_id="t_1", cancel_token=CancelToken()
    )


async def test_returns_matching_files(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    (tmp_path / "b.py").write_text("y\n")
    (tmp_path / "c.txt").write_text("z\n")
    t = GlobTool()
    result = await t.execute(GlobArgs(pattern="*.py"), _ctx(tmp_path))
    assert result.status == "ok"
    paths = set(result.text.splitlines())
    assert paths == {"a.py", "b.py"}


async def test_excludes_ignored_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "keep.py").write_text("x\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("x\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.py").write_text("x\n")
    t = GlobTool()
    result = await t.execute(GlobArgs(pattern="**/*.py"), _ctx(tmp_path))
    assert result.status == "ok"
    paths = set(result.text.splitlines())
    assert paths == {"src/keep.py"}


async def test_empty_match_returns_empty_text(tmp_path):
    t = GlobTool()
    result = await t.execute(GlobArgs(pattern="*.nonesuch"), _ctx(tmp_path))
    assert result.status == "ok"
    assert result.text == ""


async def test_caps_results_at_1000(tmp_path):
    for i in range(1050):
        (tmp_path / f"f_{i:04d}.py").write_text("x\n")
    t = GlobTool()
    result = await t.execute(GlobArgs(pattern="*.py"), _ctx(tmp_path))
    assert result.status == "ok"
    lines = result.text.splitlines()
    assert len(lines) == 1000
