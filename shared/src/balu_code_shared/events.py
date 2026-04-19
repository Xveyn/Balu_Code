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


class ToolCall(_FrozenBase):
    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str = Field(..., min_length=1)
    tool: str = Field(..., min_length=1)
    args: dict[str, Any]
    auto_approved: bool


class ToolResult(_FrozenBase):
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = Field(..., min_length=1)
    status: Literal["ok", "error"]
    bytes_out: int = Field(default=0, ge=0)
    error: str | None = None


Event = Annotated[
    UserMessage | TurnStart | Token | TurnEnd | Error | ToolCall | ToolResult,
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
    "ToolCall",
    "ToolResult",
    "TurnEnd",
    "TurnStart",
    "UserMessage",
    "parse_frame",
]
