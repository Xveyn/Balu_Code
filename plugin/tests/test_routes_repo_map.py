"""Tests for the repo-map debug routes."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin import deps
from plugin.config import BaluCodePluginConfig
from plugin.routes import build_router
from plugin.services.audit import AuditLogger
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore


@pytest.fixture
def app_factory(tmp_path):
    def _factory(root: str | None = None):
        store = ProjectStore(tmp_path / "store.db")
        if root is None:
            project_root = tmp_path / "proj"
            project_root.mkdir()
            (project_root / "a.py").write_text("def x(): pass\n")
            root_str = str(project_root)
        else:
            root_str = root
        project = store.create_project("p", root_str, None)

        audit = AuditLogger(tmp_path / "audit.db")
        deps.set_singletons(
            store=store,
            ollama=OllamaClient("http://127.0.0.1:11434"),
            plugin_config=BaluCodePluginConfig(),
            audit_log=audit,
            data_dir=tmp_path,
        )

        app = FastAPI()
        app.include_router(build_router())
        from app.api import deps as app_deps

        app.dependency_overrides[app_deps.get_current_user] = lambda: object()
        return TestClient(app), project, store

    return _factory


def test_get_repo_map_returns_envelope(app_factory):
    client, project, _ = app_factory()
    resp = client.get(f"/projects/{project.id}/repo_map")
    assert resp.status_code == 200
    body = resp.json()
    assert "<repo_map" in body["text"]
    assert body["file_count"] == 1


def test_get_repo_map_honors_budget_query(app_factory):
    client, project, _ = app_factory()
    # 4096 is within the Query(ge=64, le=32768) constraint
    resp = client.get(f"/projects/{project.id}/repo_map?budget=4096")
    assert resp.status_code == 200
    assert 'budget="4096"' in resp.json()["text"]


def test_get_repo_map_404_for_unknown_project(app_factory):
    client, _, _ = app_factory()
    resp = client.get("/projects/9999/repo_map")
    assert resp.status_code == 404


def test_get_repo_map_422_for_inaccessible_root(app_factory, tmp_path):
    client, _, _ = app_factory(root=str(tmp_path / "does_not_exist"))
    # The factory created the project at id=1 — use it
    resp = client.get("/projects/1/repo_map")
    assert resp.status_code == 422


def test_post_repo_map_rebuild_clears_cache(app_factory):
    client, project, store = app_factory()
    # Populate cache first
    client.get(f"/projects/{project.id}/repo_map")
    assert len(store.list_repo_map_entries(project.id)) == 1

    resp = client.post(f"/projects/{project.id}/repo_map/rebuild")
    assert resp.status_code == 200
    # After rebuild + the call returns the freshly-walked map, cache is repopulated
    assert resp.json()["file_count"] == 1


@pytest.mark.skip(reason="stub get_current_user permissively returns a user without credentials; auth enforcement requires real BaluHost middleware")
def test_get_repo_map_401_when_unauthenticated(tmp_path):
    """When dependency_overrides are not set, get_current_user enforces auth."""
    store = ProjectStore(tmp_path / "store.db")
    project_root = tmp_path / "proj"
    project_root.mkdir()
    project = store.create_project("p", str(project_root), None)
    audit = AuditLogger(tmp_path / "audit.db")
    deps.set_singletons(
        store=store,
        ollama=OllamaClient("http://127.0.0.1:11434"),
        plugin_config=BaluCodePluginConfig(),
        audit_log=audit,
        data_dir=tmp_path,
    )
    app = FastAPI()
    app.include_router(build_router())
    client = TestClient(app)
    resp = client.get(f"/projects/{project.id}/repo_map")
    assert resp.status_code in (401, 403)
