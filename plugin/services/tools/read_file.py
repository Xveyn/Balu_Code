"""read_file tool — read a project-root-relative text file.

Path containment is verified inline here rather than in a shared helper:
Phase 4b extracts the check to ``plugin/services/paths.py`` when the
write-side tools land and the same logic is needed twice.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from plugin.services.tools.base import ToolContext, ToolResult


class ReadFileArgs(BaseModel):
    path: str = Field(..., min_length=1, description="Path relative to project root.")
    max_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1,
        le=10 * 1024 * 1024,
        description="Maximum bytes to read (default 2 MB, cap 10 MB).",
    )


def _contained(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


class ReadFileTool:
    name = "read_file"
    description = (
        "Read the contents of a text file relative to the project root. "
        "Returns up to 2 MB by default."
    )
    args_schema = ReadFileArgs
    risk = "read"

    async def execute(self, args: ReadFileArgs, ctx: ToolContext) -> ToolResult:
        candidate = ctx.project_root / args.path
        if not _contained(candidate, ctx.project_root):
            return ToolResult(
                status="error",
                text="",
                error=f"path '{args.path}' escapes project root",
            )
        resolved = candidate.resolve(strict=False)
        if not resolved.exists():
            return ToolResult(
                status="error",
                text="",
                error=f"file '{args.path}' not found",
            )
        if not resolved.is_file():
            return ToolResult(
                status="error",
                text="",
                error=f"path '{args.path}' is not a regular file",
            )
        try:
            with resolved.open("rb") as f:
                raw = f.read(args.max_bytes)
        except OSError as exc:
            return ToolResult(
                status="error",
                text="",
                error=f"could not read '{args.path}': {exc}",
            )
        if b"\x00" in raw[:1024]:
            return ToolResult(
                status="error",
                text="",
                error=f"'{args.path}' appears to be a binary file",
            )
        text = raw.decode("utf-8", errors="replace")
        return ToolResult(status="ok", text=text, bytes_out=len(raw))


__all__ = ["ReadFileArgs", "ReadFileTool"]
