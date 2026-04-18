"""Tests for OllamaClient.list_models()."""

from __future__ import annotations

import httpx
import pytest

from plugin.services.ollama_client import (
    OllamaClient,
    OllamaModel,
    OllamaUnreachable,
)


def _mock_transport(status: int, body: dict | bytes | Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, Exception):
            raise body
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_list_models_parses_tags_response():
    tags_body = {
        "models": [
            {
                "name": "qwen2.5-coder:14b-instruct-q4_K_M",
                "size": 9100000000,
                "digest": "abc123",
                "modified_at": "2026-04-01T10:00:00Z",
                "details": {"quantization_level": "Q4_K_M"},
            },
            {
                "name": "nomic-embed-text",
                "size": 300000000,
                "digest": "def456",
                "modified_at": "2026-04-02T10:00:00Z",
                "details": {},
            },
        ]
    }
    client = OllamaClient(base_url="http://fake:11434", transport=_mock_transport(200, tags_body))
    try:
        models = await client.list_models()
    finally:
        await client.close()

    assert len(models) == 2
    assert isinstance(models[0], OllamaModel)
    assert models[0].name == "qwen2.5-coder:14b-instruct-q4_K_M"
    assert models[0].size == 9100000000
    assert models[0].quantization == "Q4_K_M"
    assert models[1].quantization is None


@pytest.mark.asyncio
async def test_list_models_retries_once_on_connect_error():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"models": []})

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        result = await client.list_models()
    finally:
        await client.close()
    assert result == []
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_list_models_raises_unreachable_after_retries():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        raise httpx.ConnectError("down")

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OllamaUnreachable):
            await client.list_models()
    finally:
        await client.close()
    assert call_count["n"] == 3


@pytest.mark.asyncio
async def test_list_models_invalid_json_raises_unreachable():
    client = OllamaClient(base_url="http://fake", transport=_mock_transport(200, b"not-json"))
    try:
        with pytest.raises(OllamaUnreachable):
            await client.list_models()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_list_models_429_raises_rate_limited():
    from plugin.services.ollama_client import OllamaRateLimited

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limit exceeded")

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OllamaRateLimited):
            await client.list_models()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_list_models_timeout_raises_timeout_error():
    from plugin.services.ollama_client import OllamaTimeoutError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OllamaTimeoutError):
            await client.list_models()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_list_models_malformed_entry_raises_unreachable():
    """A 200 response whose entries are missing required fields maps to Unreachable."""
    # Missing 'size' — should raise OllamaUnreachable with a clear message.
    body = {"models": [{"name": "m", "digest": "d"}]}
    client = OllamaClient(base_url="http://fake", transport=_mock_transport(200, body))
    try:
        with pytest.raises(OllamaUnreachable):
            await client.list_models()
    finally:
        await client.close()
