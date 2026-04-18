"""Tests for GET /projects/{project_id}/repo_map."""

from __future__ import annotations

import pytest
from app.api.deps import get_current_user
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin import BaluCodePlugin
from plugin.deps import get_ollama_client, get_project_store
from plugin.services.project_store import ProjectStore


@pytest.fixture
def store(tmp_path) -> ProjectStore:
    s = ProjectStore(tmp_path / "store.db")
    yield s
    s.close()


def _client_for(store: ProjectStore) -> TestClient:
    class _FakeOllama:
        async def list_models(self):
            return []

        async def close(self):
            pass

    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_ollama_client] = lambda: _FakeOllama()
    return TestClient(app)


def _make_project(store: ProjectStore, root: str) -> int:
    p = store.create_project(name="rm-route", root_path=root, config_yaml=None)
    return p.id


def test_repo_map_404_on_unknown_project(tmp_path, store):
    c = _client_for(store)
    r = c.get("/api/plugins/balu_code/projects/9999/repo_map")
    assert r.status_code == 404


def test_repo_map_422_when_root_missing(tmp_path, store):
    pid = _make_project(store, str(tmp_path / "does-not-exist"))
    c = _client_for(store)
    r = c.get(f"/api/plugins/balu_code/projects/{pid}/repo_map")
    assert r.status_code == 422


def test_repo_map_happy_path(tmp_path, store):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text(
        "import os\n\nclass Service:\n    def call(self) -> str:\n        return ''\n"
    )
    (tmp_path / "src" / "b.py").write_text("def helper(x: int) -> None:\n    pass\n")
    pid = _make_project(store, str(tmp_path))
    c = _client_for(store)
    r = c.get(f"/api/plugins/balu_code/projects/{pid}/repo_map")
    assert r.status_code == 200
    body = r.json()
    assert "src/a.py" in body["text"]
    assert "src/b.py" in body["text"]
    assert "class Service:" in body["text"]
    assert "def helper(x: int) -> None" in body["text"]
    assert body["file_count"] == 2
    assert body["truncated_files"] == []
    assert body["total_bytes"] == len(body["text"])


def test_repo_map_honours_budget_query(tmp_path, store):
    for i in range(20):
        (tmp_path / f"f{i}.py").write_text(f"def f{i}():\n    pass\n")
    pid = _make_project(store, str(tmp_path))
    c = _client_for(store)
    r = c.get(f"/api/plugins/balu_code/projects/{pid}/repo_map?budget=64")
    assert r.status_code == 200
    body = r.json()
    assert body["file_count"] < 20
    assert len(body["truncated_files"]) == 20 - body["file_count"]


def test_repo_map_401_when_auth_fails(tmp_path, store):
    from fastapi import HTTPException
    from fastapi import status as _status

    async def _denied():
        raise HTTPException(status_code=_status.HTTP_401_UNAUTHORIZED, detail="no")

    pid = _make_project(store, str(tmp_path))

    class _FakeOllama:
        async def list_models(self):
            return []

        async def close(self):
            pass

    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_ollama_client] = lambda: _FakeOllama()
    app.dependency_overrides[get_current_user] = _denied
    c = TestClient(app)
    assert c.get(f"/api/plugins/balu_code/projects/{pid}/repo_map").status_code == 401


def test_repo_map_422_when_budget_below_minimum(tmp_path, store):
    pid = _make_project(store, str(tmp_path))
    c = _client_for(store)
    r = c.get(f"/api/plugins/balu_code/projects/{pid}/repo_map?budget=0")
    assert r.status_code == 422


def test_repo_map_422_when_budget_above_maximum(tmp_path, store):
    pid = _make_project(store, str(tmp_path))
    c = _client_for(store)
    r = c.get(f"/api/plugins/balu_code/projects/{pid}/repo_map?budget=99999")
    assert r.status_code == 422
