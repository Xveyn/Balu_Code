"""Async HTTP/SSE client for the opencode server.

Endpoints used (see docs/superpowers/references/opencode-openapi.json):
  GET  /global/health
  POST /session
  POST /session/{id}/message    (SSE response stream — Task 9)
  POST /session/{id}/abort
"""
from __future__ import annotations

import httpx


class OpencodeClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout, transport=transport
        )

    async def __aenter__(self) -> OpencodeClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> bool:
        try:
            resp = await self._client.get("/global/health")
            return resp.status_code == 200
        except (httpx.HTTPError, OSError):
            return False


__all__ = ["OpencodeClient"]
