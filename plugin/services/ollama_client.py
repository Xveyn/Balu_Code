"""Async HTTP client for a local Ollama instance.

Phase 2 surface: ``list_models``, ``embed``, ``chat_stream``.

Error hierarchy:
    OllamaError
    ├── OllamaUnreachable     — connection refused / DNS / invalid JSON / repeated 5xx
    ├── OllamaTimeoutError    — httpx.TimeoutException
    └── OllamaRateLimited     — HTTP 429 (surfaces immediately, no retry)

Transport injection: callers MAY pass a custom ``httpx.AsyncBaseTransport``
for tests (``httpx.MockTransport``). Production omits the argument.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel


class OllamaError(Exception):
    """Base for all Ollama client errors."""


class OllamaUnreachable(OllamaError):
    """Ollama could not be reached (network, DNS, repeated 5xx, invalid JSON)."""


class OllamaTimeoutError(OllamaError):
    """Request to Ollama timed out."""


class OllamaRateLimited(OllamaError):
    """Ollama returned HTTP 429."""


class OllamaModel(BaseModel):
    name: str
    size: int
    digest: str
    quantization: str | None = None
    modified_at: str | None = None


_RETRY_DELAYS = (0.5, 1.5)  # seconds between attempts on transient errors


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
    ) -> httpx.Response:
        """Issue a non-streaming request with up to two retries on transient errors.

        Three total attempts: the initial call plus two retries spaced by the
        ``_RETRY_DELAYS`` backoffs (0.5s, 1.5s).

        Retries: ConnectError, ReadError, HTTP 503.
        Immediate: 429 -> OllamaRateLimited; TimeoutException -> OllamaTimeoutError;
                   non-503 HTTP >= 500 -> OllamaUnreachable.
        After all attempts fail: OllamaUnreachable.
        """
        attempts_made = 0
        last_exc: Exception | None = None
        for delay_before in (0.0, *_RETRY_DELAYS):
            if delay_before:
                await asyncio.sleep(delay_before)
            attempts_made += 1
            try:
                response = await self._client.request(method, path, json=json_body)
            except httpx.TimeoutException as exc:
                raise OllamaTimeoutError(str(exc)) from exc
            except (httpx.ConnectError, httpx.ReadError) as exc:
                last_exc = exc
                continue
            if response.status_code == 429:
                raise OllamaRateLimited(response.text)
            if response.status_code == 503:
                last_exc = Exception(f"503 {response.text}")
                continue
            if response.status_code >= 500:
                raise OllamaUnreachable(f"HTTP {response.status_code}: {response.text}")
            return response
        raise OllamaUnreachable(f"after {attempts_made} attempts: {last_exc}")

    async def list_models(self) -> list[OllamaModel]:
        response = await self._request_with_retry("GET", "/api/tags")
        try:
            payload: Any = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise OllamaUnreachable(f"invalid JSON from /api/tags: {exc}") from exc
        result = []
        for entry in payload.get("models", []):
            result.append(
                OllamaModel(
                    name=entry["name"],
                    size=entry["size"],
                    digest=entry["digest"],
                    quantization=(entry.get("details") or {}).get("quantization_level"),
                    modified_at=entry.get("modified_at"),
                )
            )
        return result

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Embed one or more texts via Ollama /api/embeddings.

        Empty input returns ``[]`` without touching the network.
        """
        if not texts:
            return []
        vectors: list[list[float]] = []
        for text in texts:
            response = await self._request_with_retry(
                "POST", "/api/embeddings", json_body={"model": model, "prompt": text}
            )
            try:
                payload = response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise OllamaUnreachable(f"invalid JSON from /api/embeddings: {exc}") from exc
            try:
                embedding = payload["embedding"]
            except (KeyError, TypeError) as exc:
                raise OllamaUnreachable(
                    f"missing 'embedding' field in /api/embeddings response: {exc}"
                ) from exc
            vectors.append(list(embedding))
        return vectors

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
    ) -> AsyncIterator[dict]:
        """Stream parsed NDJSON frames from /api/chat.

        Yields each frame as a dict (the raw Ollama envelope). Downstream
        callers decide which keys matter; Phase 2 does not interpret
        ``message.content`` or tool calls.

        Does not apply the retry/backoff logic used by ``_request_with_retry``:
        a stream that dies mid-way leaves the agent loop to decide whether
        to resume, so wrapping it in transparent retries would hide state.
        """
        body: dict = {"model": model, "messages": messages, "stream": True}
        if tools is not None:
            body["tools"] = tools
        if options is not None:
            body["options"] = options

        try:
            async with self._client.stream("POST", "/api/chat", json=body) as response:
                if response.status_code == 429:
                    body_bytes = await response.aread()
                    raise OllamaRateLimited(body_bytes.decode("utf-8", errors="replace"))
                if response.status_code >= 500:
                    raise OllamaUnreachable(f"HTTP {response.status_code} from /api/chat")
                async for line in response.aiter_lines():
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        yield json.loads(stripped)
                    except (json.JSONDecodeError, ValueError) as exc:
                        raise OllamaUnreachable(f"invalid JSON line from /api/chat: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(str(exc)) from exc
        except (httpx.ConnectError, httpx.ReadError) as exc:
            raise OllamaUnreachable(str(exc)) from exc


__all__ = [
    "OllamaClient",
    "OllamaError",
    "OllamaModel",
    "OllamaRateLimited",
    "OllamaTimeoutError",
    "OllamaUnreachable",
]
