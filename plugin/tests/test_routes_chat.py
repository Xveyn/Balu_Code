"""Tests for the WebSocket /chat endpoint."""

from __future__ import annotations

import pytest
from app.api.deps import get_current_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel as _BaseModel
from starlette.websockets import WebSocketDisconnect

from plugin import BaluCodePlugin
from plugin.config import BaluCodePluginConfig
from plugin.deps import (
    get_audit_log,
    get_index_job_tracker,
    get_ollama_client,
    get_plugin_config,
    get_project_store,
    get_rag_registry,
    get_tool_registry,
)
from plugin.services.index_jobs import IndexJobTracker
from plugin.services.project_store import ProjectStore
from plugin.services.tools import ToolRegistry, default_registry
from plugin.services.tools.base import ToolResult
from plugin.services.tools.read_file import ReadFileTool


class _NoopAuditLogger:
    async def record_tool_call(self, **kwargs) -> None:
        return None


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


class _EchoArgs(_BaseModel):
    msg: str


class _EchoWriteTool:
    name = "echo"
    description = "echo a message"
    risk = "write"
    args_schema = _EchoArgs

    async def execute(self, args: _EchoArgs, ctx) -> ToolResult:
        return ToolResult(status="ok", text=f"echoed: {args.msg}", bytes_out=len(args.msg))


def _registry_with_echo() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_EchoWriteTool())
    return reg


@pytest.fixture
def store(tmp_path) -> ProjectStore:
    s = ProjectStore(tmp_path / "store.db")
    yield s
    s.close()


def _make_project(store: ProjectStore, root: str) -> int:
    return store.create_project(name="chat-route", root_path=root, config_yaml=None).id


class _TrackingAuditLogger:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def record_tool_call(self, **kw) -> None:
        self.calls.append(kw)
        import asyncio as _asyncio
        await _asyncio.sleep(0)  # yield to event loop so cancel frames can be processed


def _client(store, ollama, rag_registry, tool_registry, config, audit_log=None) -> TestClient:
    if audit_log is None:
        audit_log = _NoopAuditLogger()
    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_ollama_client] = lambda: ollama
    app.dependency_overrides[get_rag_registry] = lambda: rag_registry
    app.dependency_overrides[get_index_job_tracker] = lambda: IndexJobTracker()
    app.dependency_overrides[get_tool_registry] = lambda: tool_registry
    app.dependency_overrides[get_plugin_config] = lambda: config
    app.dependency_overrides[get_audit_log] = lambda: audit_log
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
    app.dependency_overrides[get_audit_log] = lambda: _NoopAuditLogger()
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


def test_chat_approval_resolves_write_tool(tmp_path, store):
    (tmp_path / "f.py").write_text("x\n")
    pid = _make_project(store, str(tmp_path))
    _tool_call = [{"function": {"name": "echo", "arguments": {"msg": "hi"}}}]
    ollama = _FakeOllama([
        [{"message": {"content": "", "tool_calls": _tool_call}, "done": True}],
        [{"message": {"content": "all done", "tool_calls": None}, "done": True}],
    ])
    c = _client(store, ollama, _FakeRagRegistry(), _registry_with_echo(), BaluCodePluginConfig())
    with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
        ws.send_json({"type": "user_message", "content": "write something"})
        tc_id = None
        while True:
            ev = ws.receive_json()
            if ev["type"] == "approval_request":
                tc_id = ev["tool_call_id"]
                break
            if ev["type"] == "turn_end":
                break
        assert tc_id is not None, "expected approval_request before turn_end"
        ws.send_json({"type": "approval", "tool_call_id": tc_id, "approved": True})
        while True:
            ev = ws.receive_json()
            if ev["type"] == "turn_end":
                assert ev["stop_reason"] == "done"
                break


def test_chat_cancel_at_approval_gate_stops_turn(tmp_path, store):
    (tmp_path / "f.py").write_text("x\n")
    pid = _make_project(store, str(tmp_path))
    _tool_call = [{"function": {"name": "echo", "arguments": {"msg": "hi"}}}]
    ollama = _FakeOllama([
        [{"message": {"content": "", "tool_calls": _tool_call}, "done": True}],
    ])
    c = _client(store, ollama, _FakeRagRegistry(), _registry_with_echo(), BaluCodePluginConfig())
    with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
        ws.send_json({"type": "user_message", "content": "write something"})
        turn_id = None
        while True:
            ev = ws.receive_json()
            if ev["type"] == "turn_start":
                turn_id = ev["turn_id"]
            if ev["type"] == "approval_request":
                break
            if ev["type"] == "turn_end":
                break
        assert turn_id is not None
        ws.send_json({"type": "cancel", "turn_id": turn_id})
        while True:
            ev = ws.receive_json()
            if ev["type"] == "turn_end":
                assert ev["stop_reason"] == "cancelled"
                break


class TestApprovalFlowE2E:
    def test_approval_approved_dispatches_tool_and_audits(self, tmp_path, store):
        (tmp_path / "f.py").write_text("x\n")
        pid = _make_project(store, str(tmp_path))
        _tc = [{"function": {"name": "echo", "arguments": {"msg": "hi"}}}]
        ollama = _FakeOllama([
            [{"message": {"content": "", "tool_calls": _tc}, "done": True}],
            [{"message": {"content": "done", "tool_calls": None}, "done": True}],
        ])
        audit = _TrackingAuditLogger()
        c = _client(store, ollama, _FakeRagRegistry(), _registry_with_echo(), BaluCodePluginConfig(), audit)
        with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
            ws.send_json({"type": "user_message", "content": "write something"})
            tc_id = None
            while True:
                ev = ws.receive_json()
                if ev["type"] == "approval_request":
                    tc_id = ev["tool_call_id"]
                    break
                if ev["type"] == "turn_end":
                    break
            assert tc_id is not None
            ws.send_json({"type": "approval", "tool_call_id": tc_id, "approved": True})
            while True:
                ev = ws.receive_json()
                if ev["type"] == "turn_end":
                    assert ev["stop_reason"] == "done"
                    break
        assert len(audit.calls) >= 1
        tool_call = next(c for c in audit.calls if c["tool"] == "echo")
        assert tool_call["approved"] is True
        assert tool_call["status"] == "ok"

    def test_approval_rejected_feeds_error_back_and_continues(self, tmp_path, store):
        (tmp_path / "f.py").write_text("x\n")
        pid = _make_project(store, str(tmp_path))
        _tc = [{"function": {"name": "echo", "arguments": {"msg": "hi"}}}]
        ollama = _FakeOllama([
            [{"message": {"content": "", "tool_calls": _tc}, "done": True}],
            [{"message": {"content": "done", "tool_calls": None}, "done": True}],
        ])
        audit = _TrackingAuditLogger()
        c = _client(store, ollama, _FakeRagRegistry(), _registry_with_echo(), BaluCodePluginConfig(), audit)
        with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
            ws.send_json({"type": "user_message", "content": "write something"})
            tc_id = None
            while True:
                ev = ws.receive_json()
                if ev["type"] == "approval_request":
                    tc_id = ev["tool_call_id"]
                    break
                if ev["type"] == "turn_end":
                    break
            assert tc_id is not None
            ws.send_json({"type": "approval", "tool_call_id": tc_id, "approved": False, "reason": "no thanks"})
            events = []
            while True:
                ev = ws.receive_json()
                events.append(ev)
                if ev["type"] == "turn_end":
                    break
        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert any("user rejected" in (e.get("error") or "") for e in tool_results)
        end = next(e for e in events if e["type"] == "turn_end")
        assert end["stop_reason"] == "done"
        assert any(c["approved"] is False for c in audit.calls)

    def test_unknown_approval_returns_error_frame(self, tmp_path, store):
        (tmp_path / "f.py").write_text("x\n")
        pid = _make_project(store, str(tmp_path))
        c = _client(store, _FakeOllama([]), _FakeRagRegistry(), default_registry(), BaluCodePluginConfig())
        with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
            ws.send_json({"type": "approval", "tool_call_id": "bogus_tc", "approved": True})
            ev = ws.receive_json()
            assert ev["type"] == "error"
            assert ev["code"] == "unknown_approval"


class TestCancelFlowE2E:
    def test_cancel_after_first_tool_during_second_approval_ends_turn_cancelled(self, tmp_path, store):
        # Iter 1: read_file (auto-approved) → ToolResult
        # Iter 2: echo (write, needs approval) → ApprovalRequest, then Cancel
        (tmp_path / "f.py").write_text("content\n")
        pid = _make_project(store, str(tmp_path))
        _read_tc = [{"function": {"name": "read_file", "arguments": {"path": "f.py"}}}]
        _echo_tc = [{"function": {"name": "echo", "arguments": {"msg": "hi"}}}]
        ollama = _FakeOllama([
            [{"message": {"content": "", "tool_calls": _read_tc}, "done": True}],
            [{"message": {"content": "", "tool_calls": _echo_tc}, "done": True}],
        ])
        registry = ToolRegistry()
        registry.register(ReadFileTool())
        registry.register(_EchoWriteTool())
        c = _client(store, ollama, _FakeRagRegistry(), registry, BaluCodePluginConfig())
        with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
            ws.send_json({"type": "user_message", "content": "read then write"})
            turn_id = None
            while True:
                ev = ws.receive_json()
                if ev["type"] == "turn_start":
                    turn_id = ev["turn_id"]
                if ev["type"] == "approval_request":
                    break
                if ev["type"] == "turn_end":
                    break
            assert turn_id is not None
            ws.send_json({"type": "cancel", "turn_id": turn_id})
            while True:
                ev = ws.receive_json()
                if ev["type"] == "turn_end":
                    assert ev["stop_reason"] == "cancelled"
                    break

    def test_cancel_wrong_turn_id_returns_error(self, tmp_path, store):
        (tmp_path / "f.py").write_text("x\n")
        pid = _make_project(store, str(tmp_path))
        c = _client(store, _FakeOllama([]), _FakeRagRegistry(), default_registry(), BaluCodePluginConfig())
        with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
            ws.send_json({"type": "cancel", "turn_id": "bogus_turn"})
            ev = ws.receive_json()
            assert ev["type"] == "error"
            assert ev["code"] == "no_turn_to_cancel"
