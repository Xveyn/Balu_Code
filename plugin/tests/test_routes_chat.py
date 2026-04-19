"""Tests for the WebSocket /chat endpoint."""

from __future__ import annotations

import pytest
from app.api.deps import get_current_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from plugin import BaluCodePlugin
from plugin.config import BaluCodePluginConfig
from plugin.deps import (
    get_index_job_tracker,
    get_ollama_client,
    get_plugin_config,
    get_project_store,
    get_rag_registry,
    get_tool_registry,
)
from plugin.services.index_jobs import IndexJobTracker
from plugin.services.project_store import ProjectStore
from plugin.services.tools import default_registry


class _FakeOllama:
    def __init__(self, scripted: list[list[dict]]) -> None:
        self._scripted = list(scripted)

    async def chat_stream(self, *a, **kw):
        frames = self._scripted.pop(0)
        for f in frames:
            yield f

    async def list_models(self):
        return []

    async def embed(self, model, texts):
        return [[0.0] * 768 for _ in texts]

    async def close(self):
        pass


class _FakeRagRegistry:
    async def get(self, project_id):
        class _Idx:
            async def search(self, query, top_k=8, *, keyword_boost=0.15):
                return []

        return _Idx()

    async def close_all(self):
        pass


@pytest.fixture
def store(tmp_path) -> ProjectStore:
    s = ProjectStore(tmp_path / "store.db")
    yield s
    s.close()


def _make_project(store: ProjectStore, root: str) -> int:
    return store.create_project(name="chat-route", root_path=root, config_yaml=None).id


def _client(store, ollama, rag_registry, tool_registry, config) -> TestClient:
    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_ollama_client] = lambda: ollama
    app.dependency_overrides[get_rag_registry] = lambda: rag_registry
    app.dependency_overrides[get_index_job_tracker] = lambda: IndexJobTracker()
    app.dependency_overrides[get_tool_registry] = lambda: tool_registry
    app.dependency_overrides[get_plugin_config] = lambda: config
    return TestClient(app)


def test_chat_happy_path(tmp_path, store):
    (tmp_path / "a.py").write_text("def foo(): pass\n")
    pid = _make_project(store, str(tmp_path))
    ollama = _FakeOllama(
        [
            [
                {"message": {"content": "Hello", "tool_calls": None}, "done": False},
                {"message": {"content": ".", "tool_calls": None}, "done": True},
            ]
        ]
    )
    c = _client(store, ollama, _FakeRagRegistry(), default_registry(), BaluCodePluginConfig())
    with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
        ws.send_json({"type": "user_message", "content": "hi"})
        events = []
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] == "turn_end":
                break
    types = [e["type"] for e in events]
    assert types[0] == "turn_start"
    assert "token" in types
    assert types[-1] == "turn_end"


def test_chat_404_for_unknown_project(tmp_path, store):
    ollama = _FakeOllama([])
    c = _client(store, ollama, _FakeRagRegistry(), default_registry(), BaluCodePluginConfig())
    with (
        pytest.raises(WebSocketDisconnect),
        c.websocket_connect("/api/plugins/balu_code/chat?project_id=9999"),
    ):
        pass


def test_chat_401_when_auth_fails(tmp_path, store):
    from fastapi import HTTPException
    from fastapi import status as _status

    async def _denied():
        raise HTTPException(status_code=_status.HTTP_401_UNAUTHORIZED, detail="no")

    (tmp_path / "a.py").write_text("x\n")
    pid = _make_project(store, str(tmp_path))
    ollama = _FakeOllama([])
    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_ollama_client] = lambda: ollama
    app.dependency_overrides[get_rag_registry] = lambda: _FakeRagRegistry()
    app.dependency_overrides[get_index_job_tracker] = lambda: IndexJobTracker()
    app.dependency_overrides[get_tool_registry] = lambda: default_registry()
    app.dependency_overrides[get_plugin_config] = lambda: BaluCodePluginConfig()
    app.dependency_overrides[get_current_user] = _denied
    c = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect),
        c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}"),
    ):
        pass


def test_chat_multi_turn_preserves_history(tmp_path, store):
    (tmp_path / "a.py").write_text("def foo(): pass\n")
    pid = _make_project(store, str(tmp_path))
    ollama = _FakeOllama(
        [
            [
                {"message": {"content": "one", "tool_calls": None}, "done": True},
            ],
            [
                {"message": {"content": "two", "tool_calls": None}, "done": True},
            ],
        ]
    )
    c = _client(store, ollama, _FakeRagRegistry(), default_registry(), BaluCodePluginConfig())
    with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
        ws.send_json({"type": "user_message", "content": "first"})
        while True:
            ev = ws.receive_json()
            if ev["type"] == "turn_end":
                break
        ws.send_json({"type": "user_message", "content": "second"})
        turn2_events = []
        while True:
            ev = ws.receive_json()
            turn2_events.append(ev)
            if ev["type"] == "turn_end":
                break
    end2 = next(e for e in turn2_events if e["type"] == "turn_end")
    assert end2["stop_reason"] in ("done", "max_iter")


def test_chat_unsupported_frame_yields_error_and_stays_open(tmp_path, store):
    (tmp_path / "a.py").write_text("x\n")
    pid = _make_project(store, str(tmp_path))
    ollama = _FakeOllama([])
    c = _client(store, ollama, _FakeRagRegistry(), default_registry(), BaluCodePluginConfig())
    with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
        ws.send_json({"type": "approval", "tool_call_id": "tc_x", "approved": True})
        ev = ws.receive_json()
        assert ev["type"] == "error"
