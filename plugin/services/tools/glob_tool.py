"""glob tool — enumerate project files matching a POSIX-style glob.

Honors the shared IGNORE_DIRS list from ``plugin.services.repo_map``
so ``.venv``, ``node_modules``, ``__pycache__``, etc. are never
reported.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from plugin.services.repo_map import IGNORE_DIRS
from plugin.services.tools.base import ToolContext, ToolResult

_MAX_RESULTS = 1000


class GlobArgs(BaseModel):
    pattern: str = Field(
        ...,
        min_length=1,
        description="POSIX-style glob, relative to the project root.",
    )


class GlobTool:
    name = "glob"
    description = (
        "Enumerate files matching a POSIX-style glob pattern relative to "
        "the project root. Ignores .venv, node_modules, __pycache__, etc. "
        "Truncated at 1000 results."
    )
    args_schema = GlobArgs
    risk = "read"

    async def execute(self, args: GlobArgs, ctx: ToolContext) -> ToolResult:
        matches: list[str] = []
        for p in ctx.project_root.glob(args.pattern):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(ctx.project_root)
            except ValueError:
                continue
            if any(part in IGNORE_DIRS for part in rel.parts):
                continue
            matches.append(rel.as_posix())
            if len(matches) >= _MAX_RESULTS:
                break
        matches.sort()
        text = "\n".join(matches)
        return ToolResult(status="ok", text=text, bytes_out=len(text))


__all__ = ["GlobArgs", "GlobTool"]
