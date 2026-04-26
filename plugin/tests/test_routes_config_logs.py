# plugin/tests/test_routes_config_logs.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin import BaluCodePlugin
from plugin.config import BaluCodePluginConfig
from plugin.deps import get_audit_log, get_data_dir, get_plugin_config


def _make_app(tmp_path, config=None):
    cfg = config or BaluCodePluginConfig()
    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_plugin_config] = lambda: cfg
    app.dependency_overrides[get_data_dir] = lambda: tmp_path
    app.dependency_overrides[get_audit_log] = lambda: _FakeAuditLog()
    return app


class _FakeAuditLog:
    async def record_tool_call(self, **kwargs) -> None:
        pass

    async def query_recent_tool_calls(self, limit: int = 100) -> list[dict]:
        return [
            {
                "id": 1,
                "timestamp": "2026-04-26T10:00:00",
                "user": "admin",
                "action": "tool:read_file",
                "resource": "/home/user/foo.py",
                "success": True,
                "error_message": None,
                "turn_id": "t1",
                "tool_call_id": "tc1",
            }
        ]


def test_get_config_returns_current_config(tmp_path):
    cfg = BaluCodePluginConfig(chat_model="qwen2.5-coder:7b")
    client = TestClient(_make_app(tmp_path, cfg))
    r = client.get("/api/plugins/balu_code/config")
    assert r.status_code == 200
    assert r.json()["chat_model"] == "qwen2.5-coder:7b"


def test_put_config_updates_and_persists(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.put(
        "/api/plugins/balu_code/config",
        json={"chat_model": "qwen2.5-coder:7b", "temperature": 0.8},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["chat_model"] == "qwen2.5-coder:7b"
    assert body["temperature"] == 0.8
    from plugin.services.config_store import load_plugin_config
    saved = load_plugin_config(tmp_path)
    assert saved.chat_model == "qwen2.5-coder:7b"


def test_put_config_rejects_unknown_field(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.put("/api/plugins/balu_code/config", json={"unknown_field": "x"})
    assert r.status_code == 422


def test_put_config_rejects_invalid_temperature(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.put("/api/plugins/balu_code/config", json={"temperature": 5.0})
    assert r.status_code == 422


def test_get_logs_returns_entries(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/logs")
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body
    assert len(body["entries"]) == 1
    assert body["entries"][0]["action"] == "tool:read_file"


def test_get_logs_respects_limit(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/logs?limit=50")
    assert r.status_code == 200


def test_get_logs_rejects_excessive_limit(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/logs?limit=501")
    assert r.status_code == 422
