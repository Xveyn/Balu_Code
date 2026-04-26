"""write_file tool — create or overwrite a project-relative text file."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..paths import PathEscapesProjectError, resolve_within_project
from .base import ToolContext, ToolResult

_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


class WriteFileArgs(BaseModel):
    path: str = Field(..., min_length=1, description="Path relative to project root.")
    content: str = Field(..., max_length=_MAX_BYTES, description="File contents (UTF-8).")
    create_dirs: bool = Field(
        default=False,
        description="If true, create missing parent directories.",
    )


class WriteFileTool:
    name = "write_file"
    description = (
        "Create or overwrite a text file relative to the project root. "
        "Content must be UTF-8, max 2 MB. Set create_dirs=true to create "
        "missing parent directories."
    )
    args_schema = WriteFileArgs
    risk = "write"

    async def execute(self, args: WriteFileArgs, ctx: ToolContext) -> ToolResult:
        try:
            resolved = resolve_within_project(ctx.project_root, args.path)
        except PathEscapesProjectError as exc:
            return ToolResult(status="error", text="", error=str(exc))

        parent = resolved.parent
        if not parent.exists():
            if not args.create_dirs:
                return ToolResult(
                    status="error",
                    text="",
                    error=f"parent directory for '{args.path}' does not exist (set create_dirs=true)",
                )
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return ToolResult(
                    status="error",
                    text="",
                    error=f"could not create parent dirs for '{args.path}': {exc}",
                )

        existed = resolved.exists()
        encoded = args.content.encode("utf-8")
        try:
            with resolved.open("wb") as f:
                f.write(encoded)
        except OSError as exc:
            return ToolResult(
                status="error",
                text="",
                error=f"could not write '{args.path}': {exc}",
            )

        verb = "overwrote" if existed else "wrote"
        summary = f"{verb} '{args.path}' ({len(encoded)} bytes)"
        return ToolResult(status="ok", text=summary, bytes_out=len(encoded))


__all__ = ["WriteFileArgs", "WriteFileTool"]
