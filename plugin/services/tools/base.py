"""Tool Protocol + lightweight value types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from plugin.services.cancel import CancelToken


@dataclass(frozen=True)
class ToolContext:
    project_root: Path
    project_id: int
    turn_id: str
    cancel_token: CancelToken


@dataclass(frozen=True)
class ToolResult:
    status: Literal["ok", "error"]
    text: str
    bytes_out: int = 0
    error: str | None = None


class Tool(Protocol):
    name: str
    description: str
    args_schema: type[BaseModel]
    risk: Literal["read", "write", "exec", "network"]

    async def execute(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...


__all__ = ["Tool", "ToolContext", "ToolResult"]
