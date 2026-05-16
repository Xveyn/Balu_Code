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

    # Provide a config with repo_map_enabled=False so existing tests keep
    # their simple "text == raw content" assertion without needing a store.
    from plugin.config import BaluCodePluginConfig

    fake_cfg = BaluCodePluginConfig(repo_map_enabled=False)
    monkeypatch.setattr("plugin.deps.get_plugin_config", lambda: fake_cfg)

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
    fake_cfg = type("C", (), {"chat_model": "llama3:8b", "repo_map_enabled": False})()
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


def test_runtime_status_returns_health_and_pid(app_with_mocked_client, monkeypatch):
    app, _, fake_client = app_with_mocked_client
    fake_client.health = AsyncMock(return_value=True)

    class _H:
        port = 4096
        pid = 12345

    monkeypatch.setattr("plugin.deps.get_opencode_handle", lambda: _H())
    with TestClient(app) as client:
        resp = client.get("/runtime/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["healthy"] is True
        assert body["port"] == 4096
        assert body["pid"] == 12345
        assert body["binary_version"] == "1.14.50"


def test_runtime_restart_returns_501(app_with_mocked_client):
    app, _, _ = app_with_mocked_client
    with TestClient(app) as client:
        resp = client.post("/runtime/restart")
        assert resp.status_code == 501


def test_chat_v2_prepends_repo_map_envelope(monkeypatch, tmp_path):
    """The user-message text sent to opencode must start with a <repo_map> block."""
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from plugin import deps
    from plugin.config import BaluCodePluginConfig
    from plugin.routes import build_router
    from plugin.services.audit import AuditLogger
    from plugin.services.ollama_client import OllamaClient
    from plugin.services.opencode_client import OpencodeClient
    from plugin.services.project_store import ProjectStore

    # Real project + a real source file so the walker has work
    root = tmp_path / "userproj"
    root.mkdir()
    (root / "hello.py").write_text("def hello(): return 1\n")

    store = ProjectStore(tmp_path / "store.db")
    project = store.create_project("p", str(root), None)
    store.set_opencode_session_id(project.id, "ses_test")

    audit = AuditLogger(tmp_path / "audit.db")
    config = BaluCodePluginConfig()
    deps.set_singletons(
        store=store,
        ollama=OllamaClient("http://127.0.0.1:11434"),
        plugin_config=config,
        audit_log=audit,
        data_dir=tmp_path,
    )

    fake_opencode = AsyncMock(spec=OpencodeClient)
    fake_opencode.prompt = AsyncMock(
        return_value={"info": {"id": "msg"}, "parts": [{"type": "text", "text": "ok"}]}
    )
    fake_opencode.create_session = AsyncMock(return_value="ses_test")
    deps.set_opencode(handle=None, client=fake_opencode)  # type: ignore[arg-type]

    app = FastAPI()
    app.include_router(build_router())

    # Auth bypass
    from app.api import deps as app_deps

    app.dependency_overrides[app_deps.get_current_user] = lambda: object()

    client = TestClient(app)
    resp = client.post(
        f"/chat/v2/{project.id}",
        json={"messages": [{"role": "user", "content": "list the files"}]},
    )
    assert resp.status_code == 200

    args, kwargs = fake_opencode.prompt.call_args
    sent_text = kwargs["text"] if "text" in kwargs else args[1]
    assert sent_text.startswith("<repo_map")
    assert "hello.py" in sent_text
    assert "<user_message>" in sent_text
    assert "list the files" in sent_text


def test_chat_v2_skips_map_when_disabled(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from plugin import deps
    from plugin.config import BaluCodePluginConfig
    from plugin.routes import build_router
    from plugin.services.audit import AuditLogger
    from plugin.services.ollama_client import OllamaClient
    from plugin.services.opencode_client import OpencodeClient
    from plugin.services.project_store import ProjectStore

    root = tmp_path / "userproj"
    root.mkdir()
    (root / "hello.py").write_text("def hello(): return 1\n")

    store = ProjectStore(tmp_path / "store.db")
    project = store.create_project("p", str(root), None)
    store.set_opencode_session_id(project.id, "ses_test")

    audit = AuditLogger(tmp_path / "audit.db")
    config = BaluCodePluginConfig(repo_map_enabled=False)
    deps.set_singletons(
        store=store,
        ollama=OllamaClient("http://127.0.0.1:11434"),
        plugin_config=config,
        audit_log=audit,
        data_dir=tmp_path,
    )

    fake_opencode = AsyncMock(spec=OpencodeClient)
    fake_opencode.prompt = AsyncMock(
        return_value={"info": {"id": "msg"}, "parts": [{"type": "text", "text": "ok"}]}
    )
    fake_opencode.create_session = AsyncMock(return_value="ses_test")
    deps.set_opencode(handle=None, client=fake_opencode)  # type: ignore[arg-type]

    app = FastAPI()
    app.include_router(build_router())
    from app.api import deps as app_deps

    app.dependency_overrides[app_deps.get_current_user] = lambda: object()

    client = TestClient(app)
    resp = client.post(
        f"/chat/v2/{project.id}",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200

    args, kwargs = fake_opencode.prompt.call_args
    sent_text = kwargs["text"] if "text" in kwargs else args[1]
    assert sent_text == "hi"  # raw user content, no envelope
