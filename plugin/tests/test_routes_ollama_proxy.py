"""Tests for the /ollama/{path} route — auth gate, path passthrough."""

from __future__ import annotations

import httpx
import pytest
from app.api.deps import get_current_user
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from plugin.config import BaluCodePluginConfig
from plugin.deps import get_plugin_config
from plugin.routes import build_router


def _app(ollama_base_url: str = "http://upstream.test") -> FastAPI:
    """Mount the router and inject just the deps this route needs."""
    app = FastAPI()
    app.include_router(build_router(), prefix="/api/plugins/balu_code")
    cfg = BaluCodePluginConfig(ollama_base_url=ollama_base_url)
    app.dependency_overrides[get_plugin_config] = lambda: cfg
    return app


@pytest.mark.asyncio
async def test_ollama_route_requires_authentication():
    app = _app()

    async def _denied():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    app.dependency_overrides[get_current_user] = _denied
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/plugins/balu_code/ollama/api/tags")
    assert r.status_code == 401
