"""Tests for the bare Ollama proxy helper (no FastAPI route surface)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from plugin.services.ollama_proxy import _HEADERS_TO_DROP, proxy_request


def test_headers_to_drop_covers_hop_by_hop_and_auth():
    for h in (
        "connection",
        "keep-alive",
        "transfer-encoding",
        "host",
        "content-length",
        "authorization",
    ):
        assert h in _HEADERS_TO_DROP


def _wrap_proxy(base_url: str, transport: httpx.AsyncBaseTransport) -> TestClient:
    """Mount the proxy on a bare FastAPI app so we can hit it through TestClient."""
    app = FastAPI()

    @app.api_route("/proxy/{path:path}", methods=["GET", "POST"])
    async def _entry(path: str, request: Request):
        return await proxy_request(
            request, path, base_url=base_url, transport=transport
        )

    return TestClient(app)


def test_get_request_forwards_status_and_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:14b"}]})

    client = _wrap_proxy("http://upstream.test", httpx.MockTransport(handler))
    r = client.get("/proxy/api/tags")
    assert r.status_code == 200
    assert r.json() == {"models": [{"name": "qwen2.5-coder:14b"}]}
