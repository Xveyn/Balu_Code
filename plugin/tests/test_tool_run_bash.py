"""Tests for run_bash tool."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from plugin.services.cancel import CancelToken
from plugin.services.tools.base import ToolContext
from plugin.services.tools.run_bash import RunBashArgs, RunBashTool


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        project_root=tmp_path,
        project_id=1,
        turn_id="t_test",
        cancel_token=CancelToken(),
    )


@pytest.mark.asyncio
async def test_exit_zero_returns_ok(ctx: ToolContext) -> None:
    tool = RunBashTool()
    result = await tool.execute(RunBashArgs(command="echo hello"), ctx)
    assert result.status == "ok"
    assert "hello" in result.text
    assert "exit_code: 0" in result.text


@pytest.mark.asyncio
async def test_exit_nonzero_returns_error(ctx: ToolContext) -> None:
    tool = RunBashTool()
    result = await tool.execute(RunBashArgs(command="exit 3"), ctx)
    assert result.status == "error"
    assert "3" in result.text


@pytest.mark.asyncio
async def test_stdout_and_stderr_merged(ctx: ToolContext) -> None:
    tool = RunBashTool()
    result = await tool.execute(
        RunBashArgs(command="echo out; echo err >&2"),
        ctx,
    )
    assert result.status == "ok"
    assert "out" in result.text
    assert "err" in result.text


@pytest.mark.asyncio
async def test_cwd_is_project_root(ctx: ToolContext) -> None:
    (ctx.project_root / "marker").write_text("x")
    tool = RunBashTool()
    result = await tool.execute(RunBashArgs(command="ls"), ctx)
    assert result.status == "ok"
    assert "marker" in result.text


@pytest.mark.asyncio
async def test_timeout_clamped_and_enforced(ctx: ToolContext) -> None:
    tool = RunBashTool()
    result = await tool.execute(
        RunBashArgs(command="sleep 5", timeout_s=1),
        ctx,
    )
    assert result.status == "error"
    assert "timeout" in result.text.lower() or "timeout" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_cancel_token_kills_subprocess(ctx: ToolContext) -> None:
    tool = RunBashTool()

    async def canceller() -> None:
        await asyncio.sleep(0.3)
        ctx.cancel_token.cancel()

    task = asyncio.create_task(canceller())
    result = await tool.execute(
        RunBashArgs(command="sleep 10", timeout_s=30),
        ctx,
    )
    await task
    assert result.status == "error"
    assert "cancel" in (result.error or "").lower() or "cancel" in result.text.lower()


@pytest.mark.asyncio
async def test_output_tail_truncation(ctx: ToolContext) -> None:
    tool = RunBashTool()
    result = await tool.execute(
        RunBashArgs(command="yes x | head -c 524288"),
        ctx,
    )
    assert result.status == "ok"
    assert len(result.text.encode("utf-8")) <= 300_000


@pytest.mark.asyncio
async def test_env_path_is_pinned(ctx: ToolContext) -> None:
    tool = RunBashTool()
    result = await tool.execute(RunBashArgs(command="echo $PATH"), ctx)
    assert result.status == "ok"
    assert "/usr/bin" in result.text


@pytest.mark.asyncio
async def test_env_strips_baluhost_keys(ctx: ToolContext, monkeypatch) -> None:
    monkeypatch.setenv("BALUHOST_SECRET", "should-not-leak")
    tool = RunBashTool()
    result = await tool.execute(
        RunBashArgs(command="env | grep -c BALUHOST || true"),
        ctx,
    )
    assert result.status == "ok"
    last = [ln for ln in result.text.splitlines() if ln.strip()][-1]
    assert last.strip() == "0"


def test_risk_is_exec() -> None:
    assert RunBashTool.risk == "exec"
