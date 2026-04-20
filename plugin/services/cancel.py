"""Cooperative cancellation primitive.

A single ``CancelToken`` is created per turn by the WS handler and
passed into ``run_turn`` + every ``Tool.execute`` via ``ToolContext``.
The loop sprinkles ``cancel_token.check()`` between Ollama stream
chunks and before each tool dispatch (soft cancel); long-running tools
like ``run_bash`` ``await cancel_token.wait()`` from a watcher task to
kill subprocesses (hard cancel).
"""

from __future__ import annotations

import asyncio


class CancelToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        """Raise CancelledError if the token has been flipped."""
        if self._event.is_set():
            raise asyncio.CancelledError("cancelled by user")

    async def wait(self) -> None:
        """Await until the token is flipped."""
        await self._event.wait()


__all__ = ["CancelToken"]
