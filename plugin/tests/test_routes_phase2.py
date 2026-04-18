"""Tests for the Phase 2 REST routes."""

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


@pytest.fixture
def client(store: ProjectStore) -> TestClient:
    """App with plugin router mounted, ProjectStore injected, OllamaClient stubbed."""

    class _FakeOllama:
        async def list_models(self):
            return []

        async def close(self):
            pass

    fake_ollama = _FakeOllama()
    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_ollama_client] = lambda: fake_ollama
    return TestClient(app)


def test_create_project_returns_201_with_body(client):
    r = client.post(
        "/api/plugins/balu_code/projects",
        json={"name": "baluhost", "root_path": "/abs/path", "config_yaml": None},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] > 0
    assert body["name"] == "baluhost"
    assert body["root_path"] == "/abs/path"
    assert body["config_yaml"] is None


def test_create_project_with_config_yaml(client):
    r = client.post(
        "/api/plugins/balu_code/projects",
        json={
            "name": "with-config",
            "root_path": "/abs/x",
            "config_yaml": "project:\n  name: x\n",
        },
    )
    assert r.status_code == 201
    assert r.json()["config_yaml"] == "project:\n  name: x\n"


def test_create_project_rejects_relative_path(client):
    r = client.post(
        "/api/plugins/balu_code/projects",
        json={"name": "rel", "root_path": "./relative", "config_yaml": None},
    )
    assert r.status_code == 400


def test_create_project_duplicate_name_409(client):
    body = {"name": "dup", "root_path": "/a", "config_yaml": None}
    assert client.post("/api/plugins/balu_code/projects", json=body).status_code == 201
    r = client.post("/api/plugins/balu_code/projects", json=body)
    assert r.status_code == 409


def test_list_projects_empty(client):
    r = client.get("/api/plugins/balu_code/projects")
    assert r.status_code == 200
    assert r.json() == {"projects": []}


def test_list_projects_returns_created(client):
    client.post(
        "/api/plugins/balu_code/projects",
        json={"name": "a", "root_path": "/a", "config_yaml": None},
    )
    client.post(
        "/api/plugins/balu_code/projects",
        json={"name": "b", "root_path": "/b", "config_yaml": None},
    )
    r = client.get("/api/plugins/balu_code/projects")
    assert r.status_code == 200
    body = r.json()
    assert len(body["projects"]) == 2
    assert {p["name"] for p in body["projects"]} == {"a", "b"}


def test_get_project_by_id(client):
    created = client.post(
        "/api/plugins/balu_code/projects",
        json={"name": "bh", "root_path": "/abs/bh", "config_yaml": None},
    ).json()
    r = client.get(f"/api/plugins/balu_code/projects/{created['id']}")
    assert r.status_code == 200
    assert r.json() == created


def test_get_project_404_on_missing(client):
    r = client.get("/api/plugins/balu_code/projects/9999")
    assert r.status_code == 404


def test_delete_project_204(client):
    created = client.post(
        "/api/plugins/balu_code/projects",
        json={"name": "gone", "root_path": "/abs/g", "config_yaml": None},
    ).json()
    r = client.delete(f"/api/plugins/balu_code/projects/{created['id']}")
    assert r.status_code == 204
    # Subsequent GET is 404.
    r2 = client.get(f"/api/plugins/balu_code/projects/{created['id']}")
    assert r2.status_code == 404


def test_delete_project_404_on_missing(client):
    r = client.delete("/api/plugins/balu_code/projects/9999")
    assert r.status_code == 404


def test_models_happy_path(client, store, monkeypatch):
    # Rebuild a client whose fake Ollama returns models.
    from plugin.services.ollama_client import OllamaModel

    class _OllamaWithModels:
        async def list_models(self):
            return [
                OllamaModel(
                    name="qwen2.5-coder:14b",
                    size=9_000_000_000,
                    digest="abc",
                    quantization="Q4_K_M",
                    modified_at="2026-04-01T00:00:00Z",
                ),
                OllamaModel(
                    name="nomic-embed-text",
                    size=300_000_000,
                    digest="def",
                    quantization=None,
                    modified_at=None,
                ),
            ]

        async def close(self):
            pass

    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_ollama_client] = _OllamaWithModels
    c = TestClient(app)
    r = c.get("/api/plugins/balu_code/models")
    assert r.status_code == 200
    body = r.json()
    names = [m["name"] for m in body["models"]]
    assert names == ["qwen2.5-coder:14b", "nomic-embed-text"]
    assert body["models"][0]["quantization"] == "Q4_K_M"
    assert body["models"][1]["quantization"] is None


def test_models_503_when_ollama_unreachable(client, store):
    from plugin.services.ollama_client import OllamaUnreachable

    class _OllamaDown:
        async def list_models(self):
            raise OllamaUnreachable("connection refused")

        async def close(self):
            pass

    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_ollama_client] = _OllamaDown
    c = TestClient(app)
    r = c.get("/api/plugins/balu_code/models")
    assert r.status_code == 503


def test_routes_return_401_when_auth_fails(store):
    from fastapi import HTTPException
    from fastapi import status as _status

    async def _denied():
        raise HTTPException(status_code=_status.HTTP_401_UNAUTHORIZED, detail="no")

    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_current_user] = _denied
    c = TestClient(app)
    # A route that uses the auth dependency must return 401.
    assert c.get("/api/plugins/balu_code/projects").status_code == 401
    assert (
        c.post(
            "/api/plugins/balu_code/projects",
            json={"name": "x", "root_path": "/a", "config_yaml": None},
        ).status_code
        == 401
    )
