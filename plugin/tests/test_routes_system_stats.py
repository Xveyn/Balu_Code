"""Tests for GET /system, GET /turns/current, and GET /stats routes."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin import BaluCodePlugin
from plugin.config import BaluCodePluginConfig
from plugin.deps import get_audit_log, get_data_dir, get_ollama_client, get_plugin_config


class _FakeOllama:
    async def list_models(self):
        return []

    async def ps(self):
        return [{"name": "qwen2.5-coder:14b", "size_vram": 9_000_000_000, "context_length": 32768}]


class _FakeAuditLog:
    async def record_tool_call(self, **kwargs) -> None:
        pass

    async def query_recent_tool_calls(self, limit: int = 100) -> list[dict]:
        return []

    async def record_turn_end(self, **kwargs) -> None:
        pass

    async def query_stats(self, days: int = 7) -> dict:
        return {
            "last_n_days": [
                {"date": "2026-04-26", "requests": 5, "tokens_in": 10000, "tokens_out": 2000}
            ],
            "by_model": [
                {"model": "qwen2.5-coder:14b", "requests": 5, "avg_tokens_per_s": 18.5}
            ],
            "top_tools": [
                {"tool": "read_file", "calls": 20, "success_rate": 0.95}
            ],
            "approval_summary": {"auto_approved": 15, "user_approved": 3, "rejected": 1},
        }


_GPU_INFO = {
    "available": True,
    "backend": "rocm",
    "utilization_pct": 42,
    "vram_used_bytes": 9_500_000_000,
    "vram_total_bytes": 21_474_836_480,
}


def _make_app(tmp_path):
    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_plugin_config] = lambda: BaluCodePluginConfig()
    app.dependency_overrides[get_data_dir] = lambda: tmp_path
    app.dependency_overrides[get_ollama_client] = lambda: _FakeOllama()
    app.dependency_overrides[get_audit_log] = lambda: _FakeAuditLog()
    return app


# ── /system ───────────────────────────────────────────────────────────────────

def test_get_system_with_gpu(tmp_path):
    client = TestClient(_make_app(tmp_path))
    with patch("plugin.routes.get_gpu_info", return_value=_GPU_INFO):
        r = client.get("/api/plugins/balu_code/system")
    assert r.status_code == 200
    body = r.json()
    assert body["ollama"]["reachable"] is True
    assert body["ollama"]["loaded_models"][0]["name"] == "qwen2.5-coder:14b"
    assert body["gpu"]["available"] is True
    assert body["gpu"]["utilization_pct"] == 42


def test_get_system_gpu_unavailable(tmp_path):
    client = TestClient(_make_app(tmp_path))
    with patch("plugin.routes.get_gpu_info", return_value=None):
        r = client.get("/api/plugins/balu_code/system")
    assert r.status_code == 200
    assert r.json()["gpu"]["available"] is False


# ── /turns/current ────────────────────────────────────────────────────────────

def test_turns_current_idle(tmp_path):
    import plugin.services.active_turn as at
    at._active = None
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/turns/current")
    assert r.status_code == 200
    assert r.json()["active"] is False


def test_turns_current_active(tmp_path):
    from datetime import datetime, timezone
    from plugin.services.active_turn import ActiveTurn, set_active
    import plugin.services.active_turn as at
    at._active = None
    set_active(ActiveTurn(
        turn_id="t_test",
        model="qwen2.5-coder:14b",
        started_at=datetime.now(timezone.utc),
        iterations=3,
        username="sven",
    ))
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/turns/current")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True
    assert body["turn_id"] == "t_test"
    assert body["iterations"] == 3
    assert body["model"] == "qwen2.5-coder:14b"
    assert body["elapsed_seconds"] is not None
    at._active = None
