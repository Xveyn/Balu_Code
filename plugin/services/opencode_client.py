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

    async def create_session(self, *, title: str | None = None) -> str:
        """Create a new session in the opencode server's current project.

        opencode v1.14.50 does NOT accept a directory in the POST /session body.
        The session inherits its working directory from the server's project
        (set via the CWD where `opencode serve` was launched). To change project,
        the server must be restarted with a different CWD.

        Returns the session id (matches pattern ^ses).
        """
        body: dict[str, str] = {}
        if title is not None:
            body["title"] = title
        resp = await self._client.post("/session", json=body)
        resp.raise_for_status()
        return resp.json()["id"]


__all__ = ["OpencodeClient"]
