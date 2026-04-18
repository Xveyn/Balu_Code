"""Tests for OllamaClient.embed()."""
from __future__ import annotations

import httpx
import pytest

from plugin.services.ollama_client import OllamaClient, OllamaTimeoutError


@pytest.mark.asyncio
async def test_embed_single_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embeddings"
        body = request.read()
        import json as _json

        data = _json.loads(body)
        assert data["model"] == "nomic-embed-text"
        assert data["prompt"] == "hello"
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        result = await client.embed("nomic-embed-text", ["hello"])
    finally:
        await client.close()
    assert result == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_embed_multiple_texts():
    prompts_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        data = _json.loads(request.read())
        prompts_seen.append(data["prompt"])
        return httpx.Response(200, json={"embedding": [float(len(data["prompt"]))]})

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        result = await client.embed("nomic-embed-text", ["a", "bb", "ccc"])
    finally:
        await client.close()
    assert result == [[1.0], [2.0], [3.0]]
    assert prompts_seen == ["a", "bb", "ccc"]


@pytest.mark.asyncio
async def test_embed_empty_list_returns_empty():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"embedding": []})

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        result = await client.embed("nomic-embed-text", [])
    finally:
        await client.close()
    assert result == []
    assert called is False


@pytest.mark.asyncio
async def test_embed_timeout_mapped():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OllamaTimeoutError):
            await client.embed("m", ["x"])
    finally:
        await client.close()
