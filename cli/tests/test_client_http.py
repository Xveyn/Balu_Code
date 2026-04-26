"""Tests for client/http.py — uses respx to mock httpx."""
from __future__ import annotations

import httpx
import pytest
import respx

from balu_code_cli.client.http import BaluCodeHttpClient

BASE = "https://balu.example.com/api/plugins/balu_code"


@respx.mock
def test_health_returns_dict():
    respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"status": "ok", "plugin": "balu_code", "version": "0.1.0"})
    )
    client = BaluCodeHttpClient("https://balu.example.com", "bc_test")
    result = client.health()
    assert result["status"] == "ok"


@respx.mock
def test_health_sends_bearer_token():
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    BaluCodeHttpClient("https://balu.example.com", "bc_secret").health()
    assert route.calls[0].request.headers["authorization"] == "Bearer bc_secret"


@respx.mock
def test_list_models_returns_names():
    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(200, json={
            "models": [
                {"name": "llama3.1:8b", "size": 1000, "digest": "abc"},
                {"name": "codellama:7b", "size": 2000, "digest": "def"},
            ]
        })
    )
    client = BaluCodeHttpClient("https://balu.example.com", "key")
    assert client.list_models() == ["llama3.1:8b", "codellama:7b"]


@respx.mock
def test_create_project_posts_correct_body():
    route = respx.post(f"{BASE}/projects").mock(
        return_value=httpx.Response(201, json={"id": 5, "name": "myproj", "root_path": "/home/x/proj"})
    )
    client = BaluCodeHttpClient("https://balu.example.com", "key")
    result = client.create_project("myproj", "/home/x/proj")
    assert result["id"] == 5
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["name"] == "myproj"
    assert body["root_path"] == "/home/x/proj"


@respx.mock
def test_start_index_returns_job():
    respx.post(f"{BASE}/projects/3/index").mock(
        return_value=httpx.Response(202, json={"job_id": "j1", "project_id": 3, "status": "running"})
    )
    client = BaluCodeHttpClient("https://balu.example.com", "key")
    result = client.start_index(3)
    assert result["job_id"] == "j1"


@respx.mock
def test_index_status_returns_status():
    respx.get(f"{BASE}/projects/3/index/status/j1").mock(
        return_value=httpx.Response(200, json={
            "job_id": "j1", "project_id": 3, "status": "done",
            "files_total": 10, "files_processed": 10, "chunks_total": 80,
            "error": None, "started_at": None, "finished_at": None,
        })
    )
    client = BaluCodeHttpClient("https://balu.example.com", "key")
    result = client.index_status(3, "j1")
    assert result["status"] == "done"
    assert result["files_total"] == 10


@respx.mock
def test_http_error_raises():
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(401))
    client = BaluCodeHttpClient("https://balu.example.com", "bad_key")
    with pytest.raises(httpx.HTTPStatusError):
        client.health()
