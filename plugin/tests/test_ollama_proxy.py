"""Tests for the bare Ollama proxy helper (no FastAPI route surface)."""

from __future__ import annotations

import httpx
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


def test_post_request_forwards_body_bytes():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        seen["content_type"] = request.headers.get("content-type")
        return httpx.Response(200, json={"ok": True})

    client = _wrap_proxy("http://upstream.test", httpx.MockTransport(handler))
    payload = b'{"model": "qwen2.5-coder:14b", "messages": []}'
    r = client.post(
        "/proxy/api/chat",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 200
    assert seen["body"] == payload
    assert seen["content_type"] == "application/json"


def test_streaming_response_chunks_pass_through_in_order():
    chunks = [b'{"chunk":1}\n', b'{"chunk":2}\n', b'{"chunk":3}\n']

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(b"".join(chunks)))

    client = _wrap_proxy("http://upstream.test", httpx.MockTransport(handler))
    with client.stream("POST", "/proxy/api/chat") as r:
        assert r.status_code == 200
        got = b"".join(r.iter_raw())
    assert got == b"".join(chunks)


def test_authorization_header_does_not_leak_upstream():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={})

    client = _wrap_proxy("http://upstream.test", httpx.MockTransport(handler))
    r = client.get(
        "/proxy/api/tags",
        headers={"authorization": "Bearer balu_secret123"},
    )
    assert r.status_code == 200
    assert seen["authorization"] is None
