"""Async HTTP client for the opencode server.

Endpoints used (see docs/superpowers/references/opencode-openapi.json):
  GET  /global/health
  POST /session
  POST /session/{id}/message    (synchronous — blocks until turn completes)
  POST /session/{id}/abort
"""

from __future__ import annotations

import httpx


class OpencodeClient:
    def __init__(
        self,
        base_url: str,
        *,
        password: str | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        auth: httpx.Auth | None = (
            httpx.BasicAuth("opencode", password) if password else None
        )
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            auth=auth,
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

    async def prompt(
        self,
        session_id: str,
        *,
        text: str,
        model_provider: str,
        model_id: str,
    ) -> dict:
        """Send a single-text message to a session and wait for the assistant's reply.

        Uses POST /session/{id}/message which is synchronous: blocks until the
        full assistant turn is complete, then returns {info: AssistantMessage,
        parts: Part[]}. For v0.2.0 we deliberately do NOT use the async/SSE
        streaming variant (POST /session/{id}/prompt_async + GET /event SSE)
        — that's deferred to a later release.

        `model_provider` and `model_id` map onto opencode's {providerID, modelID}
        contract. For local Ollama, pass model_provider="ollama" and model_id
        like "qwen2.5-coder:14b".
        """
        body = {
            "parts": [{"type": "text", "text": text}],
            "model": {"providerID": model_provider, "modelID": model_id},
        }
        resp = await self._client.post(
            f"/session/{session_id}/message",
            json=body,
            timeout=600.0,  # turns can take minutes on local models
        )
        resp.raise_for_status()
        return resp.json()

    async def session_abort(self, session_id: str) -> None:
        """Abort an in-flight turn. Idempotent (returns 200 even if nothing running)."""
        resp = await self._client.post(f"/session/{session_id}/abort")
        resp.raise_for_status()


__all__ = ["OpencodeClient"]
