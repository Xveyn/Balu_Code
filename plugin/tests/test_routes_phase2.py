"""Tests for the Phase 2 REST routes."""
from __future__ import annotations

import pytest
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
