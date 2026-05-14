"""Tests for GET /runtime/credentials — exposes the OpenCode Basic Auth password."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from plugin.deps import set_opencode_password
from plugin.routes import build_router


@pytest.fixture
def app_with_router() -> FastAPI:
    app = FastAPI()
    app.include_router(build_router(), prefix="/api/plugins/balu_code")
    return app


@pytest.mark.asyncio
async def test_runtime_credentials_returns_username_and_password(app_with_router):
    set_opencode_password("test-pw-xyz")
    transport = ASGITransport(app=app_with_router)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/plugins/balu_code/runtime/credentials")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"username": "opencode", "password": "test-pw-xyz"}


@pytest.mark.asyncio
async def test_runtime_credentials_returns_503_when_not_initialised(app_with_router):
    # No set_opencode_password call — singleton is cleared by autouse fixture.
    transport = ASGITransport(app=app_with_router)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/plugins/balu_code/runtime/credentials")
    assert resp.status_code == 503
