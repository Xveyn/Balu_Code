"""run_bash tool — run a shell command with timeout + hard cancel.

The command string is passed as argv to /bin/bash -c, not interpolated
into a shell template from this code, so there is no injection surface
here. The approval gate upstream governs whether a command may run.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from pydantic import BaseModel, Field

from plugin.services.tools.base import ToolContext, ToolResult

_TAIL_BYTES = 128 * 1024
_GRACE_S = 2.0


class RunBashArgs(BaseModel):
    command: str = Field(..., min_length=1, description="Shell command (bash -c).")
    timeout_s: int = Field(default=60, ge=1, le=300, description="Timeout in seconds.")


class RunBashTool:
    name = "run_bash"
    description = (
        "Run a shell command (bash -c) in the project root. Combined "
        "stdout+stderr is returned (truncated head+tail for long output). "
        "Default timeout 60 s (max 300 s)."
    )
    args_schema = RunBashArgs
    risk = "exec"

    async def execute(self, args: RunBashArgs, ctx: ToolContext) -> ToolResult:
        env = _sanitised_env()
        try:
            proc = await asyncio.create_subprocess_exec(
                "/bin/bash",
                "-c",
                args.command,
                cwd=str(ctx.project_root),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as e1:
            return ToolResult(
                status="error",
                text="",
                error=f"could not spawn subprocess: {e1}",
            )

        cancel_watcher = asyncio.create_task(_watch_cancel(ctx.cancel_token, proc))
        timed_out = False

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=args.timeout_s)
        except TimeoutError:
            timed_out = True
            _kill_process_group(proc)
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_GRACE_S)
            except TimeoutError:
                proc.kill()
                stdout, _ = await proc.communicate()
        finally:
            cancel_watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_watcher

        cancelled = ctx.cancel_token.cancelled
        raw = stdout or b""
        output = _tail_truncate(raw.decode("utf-8", errors="replace"), _TAIL_BYTES)
        exit_code = proc.returncode if proc.returncode is not None else -1

        if cancelled:
            return ToolResult(
                status="error",
                text=f"exit_code: {exit_code}\ncancelled by user\n---\n{output}",
                bytes_out=len(raw),
                error="cancelled by user",
            )
        if timed_out:
            return ToolResult(
                status="error",
                text=f"exit_code: {exit_code}\ntimeout after {args.timeout_s}s\n---\n{output}",
                bytes_out=len(raw),
                error=f"timeout after {args.timeout_s}s",
            )
        header = f"exit_code: {exit_code}\n---\n"
        if exit_code == 0:
            return ToolResult(status="ok", text=header + output, bytes_out=len(raw))
        return ToolResult(
            status="error",
            text=header + output,
            bytes_out=len(raw),
            error=f"command failed with exit code {exit_code}",
        )


def _sanitised_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("BALUHOST_")}
    env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    return env


async def _watch_cancel(token, proc) -> None:
    try:
        await token.wait()
    except asyncio.CancelledError:
        return
    if proc.returncode is None:
        _kill_process_group(proc)


def _kill_process_group(proc) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _tail_truncate(s: str, budget: int) -> str:
    encoded = s.encode("utf-8")
    if len(encoded) <= 2 * budget:
        return s
    head = encoded[:budget].decode("utf-8", errors="replace")
    tail = encoded[-budget:].decode("utf-8", errors="replace")
    dropped = len(encoded) - 2 * budget
    return f"{head}\n\n... [{dropped} bytes truncated] ...\n\n{tail}"


__all__ = ["RunBashArgs", "RunBashTool"]
