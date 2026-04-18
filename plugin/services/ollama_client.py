"""Async HTTP client for a local Ollama instance.

Phase 2 surface: ``list_models``. ``embed`` and ``chat_stream`` arrive
in Tasks 7 and 8.

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
        """Issue a non-streaming request with one retry on transient errors.

        Retries: ConnectError, ReadError, HTTP 503.
        Immediate: 429 → OllamaRateLimited; TimeoutException → OllamaTimeoutError.
        After the final failed attempt: OllamaUnreachable.
        """
        last_exc: Exception | None = None
        for _attempt, delay_before in enumerate((0.0, *_RETRY_DELAYS)):
            if delay_before:
                await asyncio.sleep(delay_before)
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
        raise OllamaUnreachable(f"after {_attempt + 1} attempts: {last_exc}")

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


__all__ = [
    "OllamaClient",
    "OllamaError",
    "OllamaModel",
    "OllamaRateLimited",
    "OllamaTimeoutError",
    "OllamaUnreachable",
]
