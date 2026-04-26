"""BaluCodeWS — asyncio WebSocket client."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import websockets
from balu_code_shared.events import Event, parse_frame


def _ws_url(server_url: str, project_id: int) -> str:
    url = server_url.rstrip("/")
    url = url.replace("https://", "wss://").replace("http://", "ws://")
    return f"{url}/api/plugins/balu_code/chat?project_id={project_id}"


class BaluCodeWS:
    def __init__(self, ws) -> None:
        self._ws = ws

    async def send_message(self, content: str) -> None:
        await self._ws.send(json.dumps({"type": "user_message", "content": content}))

    async def send_approval(
        self, tool_call_id: str, approved: bool, reason: str | None = None
    ) -> None:
        payload: dict = {"type": "approval", "tool_call_id": tool_call_id, "approved": approved}
        if reason:
            payload["reason"] = reason
        await self._ws.send(json.dumps(payload))

    async def send_cancel(self, turn_id: str) -> None:
        await self._ws.send(json.dumps({"type": "cancel", "turn_id": turn_id}))

    async def receive(self) -> Event:
        raw = await self._ws.recv()
        return parse_frame(json.loads(raw))


@asynccontextmanager
async def connect(
    server_url: str, api_key: str, project_id: int
) -> AsyncIterator[BaluCodeWS]:
    url = _ws_url(server_url, project_id)
    extra = {"Authorization": f"Bearer {api_key}"}
    async with websockets.connect(url, additional_headers=extra) as ws:
        yield BaluCodeWS(ws)


__all__ = ["BaluCodeWS", "connect"]
