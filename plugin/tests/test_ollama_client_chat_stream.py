"""Tests for OllamaClient.chat_stream()."""

from __future__ import annotations

import httpx
import pytest

from plugin.services.ollama_client import OllamaClient


def _ndjson(frames: list[dict]) -> bytes:
    import json as _json

    return ("\n".join(_json.dumps(f) for f in frames) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_chat_stream_yields_parsed_frames():
    frames = [
        {"model": "m", "message": {"role": "assistant", "content": "Hello"}, "done": False},
        {"model": "m", "message": {"role": "assistant", "content": " world"}, "done": False},
        {
            "model": "m",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        import json as _json

        body = _json.loads(request.read())
        assert body["model"] == "qwen2.5-coder:14b"
        assert body["stream"] is True
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(200, content=_ndjson(frames))

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        collected = []
        async for frame in client.chat_stream(
            "qwen2.5-coder:14b",
            messages=[{"role": "user", "content": "hi"}],
        ):
            collected.append(frame)
    finally:
        await client.close()

    assert len(collected) == 3
    assert collected[0]["message"]["content"] == "Hello"
    assert collected[2]["done"] is True
    assert collected[2]["done_reason"] == "stop"


@pytest.mark.asyncio
async def test_chat_stream_forwards_tools_and_options():
    captured_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured_body.update(_json.loads(request.read()))
        return httpx.Response(200, content=_ndjson([{"done": True}]))

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        async for _ in client.chat_stream(
            "m",
            messages=[{"role": "user", "content": "x"}],
            tools=[{"type": "function", "function": {"name": "read_file"}}],
            options={"temperature": 0.2},
        ):
            pass
    finally:
        await client.close()

    assert captured_body["tools"][0]["function"]["name"] == "read_file"
    assert captured_body["options"] == {"temperature": 0.2}


@pytest.mark.asyncio
async def test_chat_stream_skips_blank_lines():
    body = b'{"message": {"content": "a"}, "done": false}\n\n{"done": true}\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        collected = []
        async for frame in client.chat_stream("m", messages=[{"role": "user", "content": "x"}]):
            collected.append(frame)
    finally:
        await client.close()
    assert len(collected) == 2


@pytest.mark.asyncio
async def test_chat_stream_429_raises_rate_limited():
    from plugin.services.ollama_client import OllamaRateLimited

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OllamaRateLimited) as excinfo:
            async for _ in client.chat_stream("m", messages=[{"role": "user", "content": "x"}]):
                pass
        # Ensure the message is str, not bytes.
        assert isinstance(excinfo.value.args[0], str)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_chat_stream_5xx_raises_unreachable():
    from plugin.services.ollama_client import OllamaUnreachable

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service down")

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OllamaUnreachable):
            async for _ in client.chat_stream("m", messages=[{"role": "user", "content": "x"}]):
                pass
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_chat_stream_timeout_raises_timeout_error():
    from plugin.services.ollama_client import OllamaTimeoutError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OllamaTimeoutError):
            async for _ in client.chat_stream("m", messages=[{"role": "user", "content": "x"}]):
                pass
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_chat_stream_connect_error_raises_unreachable():
    from plugin.services.ollama_client import OllamaUnreachable

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OllamaUnreachable):
            async for _ in client.chat_stream("m", messages=[{"role": "user", "content": "x"}]):
                pass
    finally:
        await client.close()
