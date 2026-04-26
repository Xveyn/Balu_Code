"""grep tool — regex search over project files.

Uses ripgrep (``rg``) as a subprocess when available; falls back to a
pure-Python ``re`` scan otherwise. Output format is always
``path:line:content`` (one match per line). Max 500 matches.
"""

from __future__ import annotations

import asyncio
import re
import shutil

from pydantic import BaseModel, Field

from ..repo_map import IGNORE_DIRS
from .base import ToolContext, ToolResult

_MAX_MATCHES = 500
_MAX_FILE_BYTES = 2 * 1024 * 1024


class GrepArgs(BaseModel):
    pattern: str = Field(..., min_length=1, description="Python-style regex.")
    glob: str | None = Field(default=None, description="Optional glob to restrict the search.")
    case_insensitive: bool = False


class GrepTool:
    name = "grep"
    description = (
        "Search file contents for a regex pattern. Uses ripgrep when "
        "available, else pure-Python. Honors IGNORE_DIRS. Max 500 matches."
    )
    args_schema = GrepArgs
    risk = "read"

    async def execute(self, args: GrepArgs, ctx: ToolContext) -> ToolResult:
        rg = shutil.which("rg")
        if rg is not None:
            lines = await self._run_rg(rg, args, ctx)
        else:
            lines = await asyncio.to_thread(self._run_python, args, ctx)
        text = "\n".join(lines)
        return ToolResult(status="ok", text=text, bytes_out=len(text))

    async def _run_rg(self, rg: str, args: GrepArgs, ctx: ToolContext) -> list[str]:
        cmd = [
            rg,
            "--line-number",
            "--no-heading",
            "--color=never",
            "--max-count",
            str(_MAX_MATCHES),
        ]
        if args.case_insensitive:
            cmd.append("-i")
        if args.glob is not None:
            cmd.extend(["-g", args.glob])
        for d in sorted(IGNORE_DIRS):
            cmd.extend(["-g", f"!{d}/**"])
        cmd.extend(["-e", args.pattern, str(ctx.project_root)])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
        except OSError:
            return await asyncio.to_thread(self._run_python, args, ctx)
        lines: list[str] = []
        for raw in stdout.decode("utf-8", errors="replace").splitlines():
            if not raw:
                continue
            rel = self._strip_root(raw, ctx)
            lines.append(rel)
            if len(lines) >= _MAX_MATCHES:
                break
        return lines

    def _strip_root(self, line: str, ctx: ToolContext) -> str:
        prefix = str(ctx.project_root.resolve()) + "/"
        if line.startswith(prefix):
            return line[len(prefix) :]
        return line

    def _run_python(self, args: GrepArgs, ctx: ToolContext) -> list[str]:
        flags = re.IGNORECASE if args.case_insensitive else 0
        regex = re.compile(args.pattern, flags)
        matches: list[str] = []
        if args.glob is not None:
            candidates = list(ctx.project_root.glob(args.glob))
        else:
            candidates = list(ctx.project_root.rglob("*"))
        for p in candidates:
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(ctx.project_root)
            except ValueError:
                continue
            if any(part in IGNORE_DIRS for part in rel.parts):
                continue
            try:
                with p.open("rb") as f:
                    data = f.read(_MAX_FILE_BYTES)
            except OSError:
                continue
            text = data.decode("utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{rel.as_posix()}:{i}:{line}")
                    if len(matches) >= _MAX_MATCHES:
                        return matches
        return matches


__all__ = ["GrepArgs", "GrepTool"]
