"""Tool Protocol + lightweight value types.

A tool is any object that conforms to the ``Tool`` Protocol:
- ``name``, ``description``, ``risk`` class attributes
- ``args_schema`` — a Pydantic BaseModel subclass describing the
  tool's input arguments
- async ``execute(args, ctx) -> ToolResult``

``ToolContext`` carries the minimal per-turn state a tool needs
(project_root for path resolution, project_id for logging, turn_id
for correlation). Phase 4b will extend it with approval callbacks and
audit-log hooks.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolContext:
    project_root: Path
    project_id: int
    turn_id: str


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

    async def execute(
        self, args: BaseModel, ctx: ToolContext
    ) -> ToolResult: ...


__all__ = ["Tool", "ToolContext", "ToolResult"]
