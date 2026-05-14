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
