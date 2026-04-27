"""In-memory singleton tracking the currently running agent turn."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ActiveTurn:
    turn_id: str
    model: str
    started_at: datetime
    iterations: int
    username: str


_active: ActiveTurn | None = None


def set_active(turn: ActiveTurn) -> None:
    global _active
    _active = turn


def update_iterations(turn_id: str, count: int) -> None:
    global _active
    if _active is not None and _active.turn_id == turn_id:
        _active.iterations = count


def clear_active(turn_id: str) -> None:
    global _active
    if _active is not None and _active.turn_id == turn_id:
        _active = None


def get_active() -> ActiveTurn | None:
    return _active


__all__ = ["ActiveTurn", "clear_active", "get_active", "set_active", "update_iterations"]
