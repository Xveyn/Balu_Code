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


@pytest.mark.asyncio
async def test_embed_missing_embedding_field_raises_unreachable():
    from plugin.services.ollama_client import OllamaUnreachable

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unrelated": "payload"})

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OllamaUnreachable):
            await client.embed("nomic-embed-text", ["x"])
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_embed_context_length_error_truncates_and_retries():
    """When Ollama returns 500 'context length exceeded', embed() halves the text and retries."""

    prompts_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        data = _json.loads(request.read())
        prompt = data["prompt"]
        prompts_seen.append(prompt)
        if len(prompt) > 4:
            return httpx.Response(
                500,
                json={"error": "the input length exceeds the context length"},
            )
        return httpx.Response(200, json={"embedding": [0.9]})

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        result = await client.embed("nomic-embed-text", ["abcdefghij"])
    finally:
        await client.close()

    assert result == [[0.9]]
    # First attempt: "abcdefghij" (10 chars) → 500; halved to "abcde" (5) → 500;
    # halved to "ab" (2) → 200
    assert len(prompts_seen) == 3
    assert prompts_seen[0] == "abcdefghij"
    assert len(prompts_seen[1]) == 5
    assert len(prompts_seen[2]) == 2


@pytest.mark.asyncio
async def test_embed_context_length_error_exhausted_raises():
    """If text is still too long after 10 truncations, OllamaUnreachable is raised."""
    from plugin.services.ollama_client import OllamaUnreachable

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"error": "the input length exceeds the context length"},
        )

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OllamaUnreachable, match="too long"):
            await client.embed("nomic-embed-text", ["x" * 1000])
    finally:
        await client.close()
