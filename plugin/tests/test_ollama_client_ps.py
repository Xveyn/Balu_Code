"""Tests for OllamaClient.ps()."""

from __future__ import annotations

import httpx
import pytest

from plugin.services.ollama_client import OllamaClient


def _transport(status: int, body: dict | Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_ps_returns_loaded_models():
    body = {
        "models": [
            {"name": "qwen2.5-coder:14b", "size_vram": 9_200_000_000, "context_length": 32768},
            {"name": "nomic-embed-text", "size_vram": 300_000_000, "context_length": None},
        ]
    }
    client = OllamaClient(transport=_transport(200, body))
    try:
        models = await client.ps()
    finally:
        await client.close()
    assert len(models) == 2
    assert models[0]["name"] == "qwen2.5-coder:14b"
    assert models[0]["size_vram"] == 9_200_000_000
    assert models[1]["context_length"] is None


@pytest.mark.asyncio
async def test_ps_returns_empty_list_when_no_models():
    client = OllamaClient(transport=_transport(200, {"models": []}))
    try:
        models = await client.ps()
    finally:
        await client.close()
    assert models == []


@pytest.mark.asyncio
async def test_ps_returns_empty_on_unreachable():
    client = OllamaClient(transport=_transport(500, {"error": "fail"}))
    try:
        models = await client.ps()
    finally:
        await client.close()
    assert models == []
