"""Tests for CancelToken."""
from __future__ import annotations

import asyncio

import pytest

from plugin.services.cancel import CancelToken


def test_starts_not_cancelled() -> None:
    tok = CancelToken()
    assert tok.cancelled is False


def test_cancel_sets_flag() -> None:
    tok = CancelToken()
    tok.cancel()
    assert tok.cancelled is True


def test_check_raises_when_cancelled() -> None:
    tok = CancelToken()
    tok.cancel()
    with pytest.raises(asyncio.CancelledError):
        tok.check()


def test_check_is_noop_when_not_cancelled() -> None:
    tok = CancelToken()
    tok.check()


@pytest.mark.asyncio
async def test_wait_blocks_until_cancelled() -> None:
    tok = CancelToken()
    events: list[str] = []

    async def waiter() -> None:
        await tok.wait()
        events.append("wait_returned")

    async def canceller() -> None:
        await asyncio.sleep(0.01)
        tok.cancel()
        events.append("cancelled")

    async with asyncio.TaskGroup() as tg:
        tg.create_task(waiter())
        tg.create_task(canceller())

    assert events == ["cancelled", "wait_returned"]


@pytest.mark.asyncio
async def test_wait_returns_immediately_if_already_cancelled() -> None:
    tok = CancelToken()
    tok.cancel()
    await asyncio.wait_for(tok.wait(), timeout=0.1)
