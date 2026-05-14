# plugin/tests/test_routes_chat_v2.py
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_mocked_client(monkeypatch):
    from plugin.routes import build_router

    fake_client = AsyncMock()
    fake_client.prompt = AsyncMock(
        return_value={
            "info": {"id": "msg_xyz"},
            "parts": [
                {"id": "prt_a", "type": "text", "text": "Sure, let me check."},
                {
                    "id": "prt_b",
                    "type": "tool",
                    "tool": "glob",
                    "callID": "call_1",
                    "input": {"pattern": "*.py"},
                    "state": {"status": "completed"},
                },
                {"id": "prt_c", "type": "text", "text": "Found 5 files."},
            ],
        }
    )
    fake_client.session_abort = AsyncMock()

    fake_bridge = AsyncMock()
    fake_bridge.get_or_create = AsyncMock(return_value="ses_abc")

    monkeypatch.setattr("plugin.deps.get_opencode_client", lambda: fake_client)
    monkeypatch.setattr("plugin.routes._session_bridge", lambda: fake_bridge)

    audit_calls = []
    fake_audit = AsyncMock()

    async def record(**kwargs):
        audit_calls.append(kwargs)

    fake_audit.record_tool_call.side_effect = record
    monkeypatch.setattr("plugin.deps.get_audit_log", lambda: fake_audit)

    app = FastAPI()
    app.include_router(build_router())
    return app, audit_calls, fake_client


def test_chat_v2_returns_json_and_logs_tool_calls(app_with_mocked_client):
    app, audit_calls, fake_client = app_with_mocked_client
    with TestClient(app) as client:
        resp = client.post(
            "/chat/v2/1",
            json={
                "messages": [{"role": "user", "content": "list py files"}],
                "model": "ollama/qwen2.5-coder:14b",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "parts" in body
    assert "Sure" in body["parts"][0]["text"]
    # tool part was logged
    assert any(c.get("tool") == "glob" for c in audit_calls), audit_calls
    # prompt was called with correct args
    args, kwargs = fake_client.prompt.call_args
    assert kwargs["text"] == "list py files"
    assert kwargs["model_provider"] == "ollama"
    assert kwargs["model_id"] == "qwen2.5-coder:14b"


def test_chat_v2_cancel_calls_session_abort(app_with_mocked_client):
    app, _, fake_client = app_with_mocked_client
    with TestClient(app) as client:
        resp = client.post("/chat/v2/1/cancel")
    assert resp.status_code == 200
    fake_client.session_abort.assert_awaited_once_with("ses_abc")


def test_chat_v2_uses_plugin_default_model_when_not_provided(app_with_mocked_client, monkeypatch):
    app, _, fake_client = app_with_mocked_client
    fake_cfg = type("C", (), {"chat_model": "llama3:8b"})()
    monkeypatch.setattr("plugin.deps.get_plugin_config", lambda: fake_cfg)
    with TestClient(app) as client:
        resp = client.post(
            "/chat/v2/1",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 200
    _, kwargs = fake_client.prompt.call_args
    assert kwargs["model_provider"] == "ollama"
    assert kwargs["model_id"] == "llama3:8b"
