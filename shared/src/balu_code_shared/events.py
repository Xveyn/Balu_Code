"""WebSocket event envelopes shared by the Balu Code plugin and CLI.

Each envelope has a literal ``type`` discriminator. ``parse_frame`` uses
a Pydantic discriminated union to dispatch an incoming dict to the right
model, which is the single source of truth both sides rely on.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _FrozenBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class UserMessage(_FrozenBase):
    type: Literal["user_message"] = "user_message"
    content: str = Field(..., min_length=1)


class TurnStart(_FrozenBase):
    type: Literal["turn_start"] = "turn_start"
    turn_id: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    context_tokens: int = Field(..., ge=0)


class Token(_FrozenBase):
    type: Literal["token"] = "token"
    content: str


StopReason = Literal["done", "max_iter", "error", "cancelled"]


class TurnEnd(_FrozenBase):
    type: Literal["turn_end"] = "turn_end"
    turn_id: str = Field(..., min_length=1)
    total_tokens: int = Field(..., ge=0)
    iterations: int = Field(..., ge=0)
    stop_reason: StopReason


class Error(_FrozenBase):
    type: Literal["error"] = "error"
    code: str = Field(..., min_length=1)
    message: str


Event = Annotated[
    UserMessage | TurnStart | Token | TurnEnd | Error,
    Field(discriminator="type"),
]


_adapter: TypeAdapter[Event] = TypeAdapter(Event)


def parse_frame(data: dict[str, Any]) -> Event:
    """Deserialise a dict-shaped WebSocket frame into the matching Event model."""
    return _adapter.validate_python(data)


__all__ = [
    "Error",
    "Event",
    "StopReason",
    "Token",
    "TurnEnd",
    "TurnStart",
    "UserMessage",
    "parse_frame",
]
