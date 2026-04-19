"""Tests for POST /projects/{id}/index."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from app.api.deps import get_current_user
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin import BaluCodePlugin
from plugin.deps import (
    get_index_job_tracker,
    get_ollama_client,
    get_project_store,
    get_rag_registry,
)
from plugin.services.index_jobs import IndexJobTracker, JobStatus
from plugin.services.project_store import ProjectStore
from plugin.services.rag_index import RagIndex


class _FakeOllama:
    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 768 for _ in texts]

    async def list_models(self):
        return []

    async def close(self) -> None:
        pass


class _FakeRagRegistry:
    def __init__(self, tmp_path: Path):
        self._tmp = tmp_path
        self._indices: dict[int, RagIndex] = {}

    async def get(self, project_id: int) -> RagIndex:
        idx = self._indices.get(project_id)
        if idx is None:
            idx = RagIndex(self._tmp / f"rag_{project_id}.db", "nomic-embed-text", _FakeOllama())
            await idx.open()
            self._indices[project_id] = idx
        return idx

    async def close_all(self) -> None:
        for i in self._indices.values():
            await i.close()
        self._indices.clear()


@pytest.fixture
def store(tmp_path) -> ProjectStore:
    s = ProjectStore(tmp_path / "store.db")
    yield s
    s.close()


def _make_project(store: ProjectStore, root: str, name: str = "idx-route") -> int:
    p = store.create_project(name=name, root_path=root, config_yaml=None)
    return p.id


def _client(store, rag_registry, tracker) -> TestClient:
    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_ollama_client] = lambda: _FakeOllama()
    app.dependency_overrides[get_rag_registry] = lambda: rag_registry
    app.dependency_overrides[get_index_job_tracker] = lambda: tracker
    return TestClient(app)


async def _wait_status(
    tracker: IndexJobTracker, job_id: str, target: JobStatus, timeout: float = 3.0
):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        j = tracker.get_job(job_id)
        if j is not None and j.status == target:
            return j
        await asyncio.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not reach {target} in {timeout}s")


def test_post_index_404_on_unknown_project(tmp_path, store):
    registry = _FakeRagRegistry(tmp_path)
    tracker = IndexJobTracker()
    c = _client(store, registry, tracker)
    r = c.post("/api/plugins/balu_code/projects/9999/index")
    assert r.status_code == 404


@pytest.mark.skip(reason="status route added in Task 11")
def test_post_index_202_and_job_transitions_to_done(tmp_path, store):
    (tmp_path / "a.py").write_text("def foo(): pass\n")
    pid = _make_project(store, str(tmp_path))
    registry = _FakeRagRegistry(tmp_path / "rag")
    tracker = IndexJobTracker()
    c = _client(store, registry, tracker)

    r = c.post(f"/api/plugins/balu_code/projects/{pid}/index")
    assert r.status_code == 202
    body = r.json()
    assert body["project_id"] == pid
    assert body["status"] in ("queued", "running", "done")

    # Poll via status endpoint until DONE.
    job_id = body["job_id"]
    for _ in range(300):
        rs = c.get(f"/api/plugins/balu_code/projects/{pid}/index/status/{job_id}")
        assert rs.status_code == 200
        if rs.json()["status"] in ("done", "error"):
            break
        import time

        time.sleep(0.02)
    final = rs.json()
    assert final["status"] == "done"
    assert final["files_processed"] == 1
    assert final["chunks_total"] >= 1


def test_post_index_409_when_already_running(tmp_path, store):
    (tmp_path / "a.py").write_text("def foo(): pass\n")
    pid = _make_project(store, str(tmp_path))
    registry = _FakeRagRegistry(tmp_path / "rag")
    tracker = IndexJobTracker()

    # Inject a fake running job directly so the 409 path is deterministic.
    from plugin.services.index_jobs import IndexJob

    fake = IndexJob(id="x", project_id=pid, status=JobStatus.RUNNING)
    tracker._jobs["x"] = fake  # test-only: directly inject a live job

    c = _client(store, registry, tracker)
    r = c.post(f"/api/plugins/balu_code/projects/{pid}/index")
    assert r.status_code == 409


def test_post_index_401_when_auth_fails(tmp_path, store):
    from fastapi import HTTPException
    from fastapi import status as _status

    async def _denied():
        raise HTTPException(status_code=_status.HTTP_401_UNAUTHORIZED, detail="no")

    pid = _make_project(store, str(tmp_path))
    registry = _FakeRagRegistry(tmp_path / "rag")
    tracker = IndexJobTracker()

    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_ollama_client] = lambda: _FakeOllama()
    app.dependency_overrides[get_rag_registry] = lambda: registry
    app.dependency_overrides[get_index_job_tracker] = lambda: tracker
    app.dependency_overrides[get_current_user] = _denied
    c = TestClient(app)
    r = c.post(f"/api/plugins/balu_code/projects/{pid}/index")
    assert r.status_code == 401


def test_status_404_on_unknown_job(tmp_path, store):
    pid = _make_project(store, str(tmp_path))
    registry = _FakeRagRegistry(tmp_path / "rag")
    tracker = IndexJobTracker()
    c = _client(store, registry, tracker)
    r = c.get(f"/api/plugins/balu_code/projects/{pid}/index/status/nonexistent")
    assert r.status_code == 404


def test_status_200_for_done_job(tmp_path, store):
    """Test that status endpoint returns 200 for a completed job."""
    from plugin.services.index_jobs import IndexJob

    pid = _make_project(store, str(tmp_path), name="proj-done")
    registry = _FakeRagRegistry(tmp_path / "rag")
    tracker = IndexJobTracker()

    # Inject a completed job directly
    job = IndexJob(
        id="j-done",
        project_id=pid,
        status=JobStatus.DONE,
        files_total=1,
        files_processed=1,
        chunks_total=5,
    )
    tracker._jobs["j-done"] = job

    c = _client(store, registry, tracker)
    r = c.get(f"/api/plugins/balu_code/projects/{pid}/index/status/j-done")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["files_processed"] == 1
    assert body["chunks_total"] == 5


def test_status_404_when_job_belongs_to_different_project(tmp_path, store):
    from plugin.services.index_jobs import IndexJob

    _make_project(store, str(tmp_path), name="proj1")
    other_pid = _make_project(store, str(tmp_path / "sub"), name="proj2")

    registry = _FakeRagRegistry(tmp_path / "rag")
    tracker = IndexJobTracker()
    injected = IndexJob(id="j-other", project_id=9999, status=JobStatus.DONE)
    tracker._jobs["j-other"] = injected
    c = _client(store, registry, tracker)
    r = c.get(f"/api/plugins/balu_code/projects/{other_pid}/index/status/j-other")
    assert r.status_code == 404
