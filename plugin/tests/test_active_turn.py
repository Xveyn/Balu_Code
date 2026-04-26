"""Tests for plugin.services.active_turn singleton."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import plugin.services.active_turn as at
from plugin.services.active_turn import (
    ActiveTurn,
    clear_active,
    get_active,
    set_active,
    update_iterations,
)


@pytest.fixture(autouse=True)
def _reset():
    at._active = None
    yield
    at._active = None


def _turn(turn_id: str = "t_abc") -> ActiveTurn:
    return ActiveTurn(
        turn_id=turn_id,
        model="qwen2.5-coder:14b",
        started_at=datetime.now(timezone.utc),
        iterations=0,
        username="sven",
    )


def test_get_active_returns_none_initially():
    assert get_active() is None


def test_set_then_get_returns_turn():
    t = _turn()
    set_active(t)
    assert get_active() is t


def test_clear_active_removes_turn():
    set_active(_turn("t1"))
    clear_active("t1")
    assert get_active() is None


def test_clear_wrong_turn_id_is_noop():
    t = _turn("t1")
    set_active(t)
    clear_active("t_other")
    assert get_active() is t


def test_update_iterations_increments_count():
    t = _turn("t1")
    set_active(t)
    update_iterations("t1", 3)
    assert get_active().iterations == 3


def test_update_iterations_wrong_turn_id_is_noop():
    t = _turn("t1")
    set_active(t)
    update_iterations("t_other", 99)
    assert get_active().iterations == 0
