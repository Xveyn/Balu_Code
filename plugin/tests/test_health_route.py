"""Tests for the /health route."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin import BaluCodePlugin


def _client() -> TestClient:
    """Mount the plugin's router on a bare FastAPI app (mirrors what BaluHost does)."""
    app = FastAPI()
    plugin = BaluCodePlugin()
    router = plugin.get_router()
    assert router is not None, "plugin must provide a router"
    app.include_router(router, prefix="/api/plugins/balu_code")
    return TestClient(app)


def test_health_returns_200():
    r = _client().get("/api/plugins/balu_code/health")
    assert r.status_code == 200


def test_health_body_shape():
    r = _client().get("/api/plugins/balu_code/health")
    body = r.json()
    assert body["status"] == "ok"
    assert body["plugin"] == "balu_code"
    assert body["version"]
    assert isinstance(body["version"], str)
