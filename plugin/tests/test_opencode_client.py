# plugin/tests/test_opencode_client.py
from __future__ import annotations

import httpx
import pytest
import respx

from plugin.services.opencode_client import OpencodeClient


@pytest.mark.asyncio
async def test_health_returns_true_on_200():
    async with OpencodeClient("http://127.0.0.1:4096") as client:
        with respx.mock(base_url="http://127.0.0.1:4096") as mock:
            mock.get("/global/health").mock(return_value=httpx.Response(200, json={}))
            assert await client.health() is True


@pytest.mark.asyncio
async def test_health_returns_false_on_connection_error():
    async with OpencodeClient("http://127.0.0.1:1") as client:
        assert await client.health() is False


@pytest.mark.asyncio
async def test_create_session_returns_id():
    async with OpencodeClient("http://127.0.0.1:4096") as client:
        with respx.mock(base_url="http://127.0.0.1:4096") as mock:
            route = mock.post("/session").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "id": "ses_abc123",
                        "time": {"created": 0, "updated": 0},
                        "version": "1.14.50",
                    },
                )
            )
            session_id = await client.create_session()
            assert session_id == "ses_abc123"
            assert route.called


@pytest.mark.asyncio
async def test_create_session_passes_title_when_provided():
    async with OpencodeClient("http://127.0.0.1:4096") as client:
        with respx.mock(base_url="http://127.0.0.1:4096") as mock:
            route = mock.post("/session").mock(
                return_value=httpx.Response(
                    200,
                    json={"id": "ses_xyz", "time": {"created": 0, "updated": 0}, "version": "1.14.50"},
                )
            )
            await client.create_session(title="my project chat")
            body = route.calls.last.request.read()
            assert b"my project chat" in body
