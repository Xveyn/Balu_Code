"""apply_patch tool — apply a unified diff via unidiff.

Multi-file diffs are validated up-front against current file content;
if any hunk doesn't match, nothing is written (no partial applies).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from unidiff import PatchSet

from plugin.services.paths import PathEscapesProjectError, resolve_within_project
from plugin.services.tools.base import ToolContext, ToolResult

_DEV_NULL = "/dev/null"


class ApplyPatchArgs(BaseModel):
    diff: str = Field(..., min_length=1, description="Unified-diff text.")


class ApplyPatchTool:
    name = "apply_patch"
    description = (
        "Apply a unified-diff patch to one or more files (multi-file patches "
        "supported). Use --- /dev/null to create, +++ /dev/null to delete. "
        "Fails atomically — if any hunk mismatches, no file is modified."
    )
    args_schema = ApplyPatchArgs
    risk = "write"

    async def execute(self, args: ApplyPatchArgs, ctx: ToolContext) -> ToolResult:
        try:
            patch_set = PatchSet.from_string(args.diff)
        except Exception as exc:
            return ToolResult(
                status="error",
                text="",
                error=f"could not parse diff: {exc}",
            )

        if len(patch_set) == 0:
            return ToolResult(
                status="error",
                text="",
                error="diff contains no files",
            )

        planned: list[tuple[Path, str, bytes | None]] = []
        hunks_total = 0

        for patched_file in patch_set:
            source = patched_file.source_file or ""
            target = patched_file.target_file or ""

            is_create = source == _DEV_NULL or source.endswith(_DEV_NULL)
            is_delete = target == _DEV_NULL or target.endswith(_DEV_NULL)

            rel_source = _strip_prefix(source) if not is_create else None
            rel_target = _strip_prefix(target) if not is_delete else None
            rel = rel_target or rel_source
            if rel is None:
                return ToolResult(
                    status="error",
                    text="",
                    error="diff has neither source nor target path",
                )

            try:
                resolved = resolve_within_project(ctx.project_root, rel)
            except PathEscapesProjectError as e2:
                return ToolResult(status="error", text="", error=str(e2))

            if is_delete:
                if not resolved.exists():
                    return ToolResult(
                        status="error",
                        text="",
                        error=f"cannot delete '{rel}': file does not exist",
                    )
                planned.append((resolved, "delete", None))
                hunks_total += len(patched_file)
                continue

            if is_create:
                if resolved.exists():
                    return ToolResult(
                        status="error",
                        text="",
                        error=f"cannot create '{rel}': file already exists",
                    )
                pieces: list[str] = []
                for hunk in patched_file:
                    for line in hunk:
                        if line.is_added:
                            pieces.append(line.value)
                planned.append((resolved, "create", "".join(pieces).encode("utf-8")))
                hunks_total += len(patched_file)
                continue

            try:
                current = resolved.read_text(encoding="utf-8")
            except OSError as exc:
                return ToolResult(
                    status="error",
                    text="",
                    error=f"could not read '{rel}' for patching: {exc}",
                )
            try:
                new_text = _apply_hunks_to_text(current, patched_file)
            except _HunkMismatch as exc:
                return ToolResult(
                    status="error",
                    text="",
                    error=f"patch to '{rel}' did not apply cleanly: {exc}",
                )
            planned.append((resolved, "modify", new_text.encode("utf-8")))
            hunks_total += len(patched_file)

        changed: list[str] = []
        for resolved, action, new_bytes in planned:
            try:
                rel_display = str(resolved.relative_to(ctx.project_root.resolve()))
            except ValueError:
                rel_display = str(resolved)

            if action == "delete":
                try:
                    resolved.unlink()
                except OSError as exc:
                    return ToolResult(
                        status="error",
                        text="",
                        error=f"could not delete '{rel_display}': {exc}",
                    )
                changed.append(f"-{rel_display}")
                continue

            try:
                resolved.parent.mkdir(parents=True, exist_ok=True)
                with resolved.open("wb") as f:
                    f.write(new_bytes or b"")
            except OSError as exc:
                return ToolResult(
                    status="error",
                    text="",
                    error=f"could not write '{rel_display}': {exc}",
                )
            changed.append(f"{'+' if action == 'create' else '~'}{rel_display}")

        bytes_out = sum(len(b or b"") for _, _, b in planned)
        summary = (
            f"applied {hunks_total} hunk(s) across {len(changed)} file(s): "
            + ", ".join(changed)
        )
        return ToolResult(status="ok", text=summary, bytes_out=bytes_out)


def _strip_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


class _HunkMismatch(Exception):
    """Raised when a hunk's context doesn't match the current file."""


def _apply_hunks_to_text(current: str, patched_file) -> str:
    lines = current.splitlines(keepends=True)
    result: list[str] = []
    cursor = 0

    for hunk in patched_file:
        src_start = max(hunk.source_start - 1, 0)
        if src_start < cursor:
            raise _HunkMismatch("hunk starts before cursor (overlap or out-of-order hunks)")
        result.extend(lines[cursor:src_start])
        cursor = src_start

        for line in hunk:
            if line.is_context or line.is_removed:
                if cursor >= len(lines):
                    raise _HunkMismatch(
                        f"expected line {cursor + 1} but file has only {len(lines)} lines"
                    )
                actual = lines[cursor]
                expected = line.value
                if actual.rstrip("\r\n") != expected.rstrip("\r\n"):
                    raise _HunkMismatch(
                        f"at line {cursor + 1}: expected {expected.rstrip()!r}, got {actual.rstrip()!r}"
                    )
                if line.is_context:
                    result.append(actual)
                cursor += 1
            elif line.is_added:
                result.append(line.value)

    result.extend(lines[cursor:])
    return "".join(result)


__all__ = ["ApplyPatchArgs", "ApplyPatchTool"]
