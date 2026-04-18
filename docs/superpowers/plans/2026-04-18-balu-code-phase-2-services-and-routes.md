# Balu Code — Phase 2: Ollama Client, Project Store, Basic Routes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the `balu_code` plugin with a persistent SQLite-backed project store, an async Ollama HTTP client, and the first five authenticated REST routes (`POST|GET|GET/{id}|DELETE /projects`, `GET /models`). Single-user semantics — the authenticated user is resolved via `Depends(get_current_user)` but does not scope project access.

**Architecture:** Singletons (`ProjectStore`, `OllamaClient`) live in `plugin/deps.py` module globals, set by `BaluCodePlugin.on_startup()` and exposed to routes via FastAPI dependency functions so tests can override them. `project_store` uses synchronous `sqlite3` under `asyncio.to_thread(...)`. `ollama_client` uses `httpx.AsyncClient` with a test-only `transport=MockTransport` injection point. Authentication is resolved by a minimal BaluHost stub extension (`app/api/deps.py` + `app/schemas/user.py`) that mirrors the real `get_current_user` surface.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, httpx (async + MockTransport), sqlite3 (stdlib), pytest + pytest-asyncio.

**Parent spec:** [`docs/superpowers/specs/2026-04-18-balu-code-phase-2-design.md`](../specs/2026-04-18-balu-code-phase-2-design.md)

---

## File Structure (this phase)

```
Balu_Code/
├── plugin/
│   ├── __init__.py                                         ← modified (Task 10)
│   ├── config.py                                           ← new (Task 3)
│   ├── data_dir.py                                         ← new (Task 4)
│   ├── deps.py                                             ← new (Task 9)
│   ├── services/
│   │   ├── __init__.py                                     ← new (Task 5)
│   │   ├── ollama_client.py                                ← new (Tasks 6, 7, 8)
│   │   └── project_store.py                                ← new (Task 5)
│   └── tests/
│       ├── fixtures/baluhost_stub/app/
│       │   ├── api/__init__.py                             ← new (Task 2)
│       │   ├── api/deps.py                                 ← new (Task 2)
│       │   ├── schemas/__init__.py                         ← new (Task 2)
│       │   └── schemas/user.py                             ← new (Task 2)
│       ├── test_config.py                                  ← new (Task 3)
│       ├── test_data_dir.py                                ← new (Task 4)
│       ├── test_project_store.py                           ← new (Task 5)
│       ├── test_ollama_client_list_models.py               ← new (Task 6)
│       ├── test_ollama_client_embed.py                     ← new (Task 7)
│       ├── test_ollama_client_chat_stream.py               ← new (Task 8)
│       ├── test_plugin_lifecycle.py                        ← new (Task 9)
│       └── test_routes_phase2.py                           ← new (Tasks 10, 11, 12, 13)
```

Task 1 is workspace prep (install `pytest-asyncio` into the dev venv); Task 14 is end-of-phase verification.

---

## Task 1: Install `pytest-asyncio` into the dev venv

The plan uses async route tests (`httpx.AsyncClient`, FastAPI streaming) that need `pytest-asyncio`. `plugin/pyproject.toml` already lists it as a dev dep (added in Phase 1), but an explicit install of the updated extras makes sure the running venv matches.

**Files:** none.

- [ ] **Step 1: Activate the venv and refresh plugin dev deps**

Run:
```bash
source .venv/bin/activate
pip install -e "plugin[dev]"
```
Expected: `pytest-asyncio` appears in `pip list` (installed in Phase 1; this is a no-op unless the venv drifted).

- [ ] **Step 2: Configure pytest-asyncio default mode**

pytest-asyncio v1 requires an explicit mode or tests emit DeprecationWarnings. Edit the workspace `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["shared/tests", "plugin/tests", "cli/tests", "scripts/tests"]
pythonpath = ["."]
addopts = "-ra -q --strict-markers --import-mode=importlib"
asyncio_mode = "auto"
```

The new line is `asyncio_mode = "auto"`.

- [ ] **Step 3: Verify existing tests still pass**

Run: `pytest`
Expected: 34 passed, 0 warnings (asyncio warnings silenced).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "test: enable pytest-asyncio auto mode for upcoming async route tests"
```

---

## Task 2: Extend BaluHost stub with `app.api.deps.get_current_user` + `UserPublic`

**Files:**
- Create: `plugin/tests/fixtures/baluhost_stub/app/schemas/__init__.py` (empty)
- Create: `plugin/tests/fixtures/baluhost_stub/app/schemas/user.py`
- Create: `plugin/tests/fixtures/baluhost_stub/app/api/__init__.py` (empty)
- Create: `plugin/tests/fixtures/baluhost_stub/app/api/deps.py`

This is the stub surface the real `app.api.deps.get_current_user` exposes (see `/opt/baluhost/backend/app/api/deps.py:30-77`). The stub returns a fixed admin-like user; tests that need 401 override the dependency in the FastAPI app.

- [ ] **Step 1: Create empty package markers**

Run:
```bash
touch plugin/tests/fixtures/baluhost_stub/app/schemas/__init__.py
mkdir -p plugin/tests/fixtures/baluhost_stub/app/api
touch plugin/tests/fixtures/baluhost_stub/app/api/__init__.py
```

- [ ] **Step 2: Create `app/schemas/user.py`**

```python
"""Stub of BaluHost's app.schemas.user. Minimal surface used by balu_code."""
from __future__ import annotations

from pydantic import BaseModel


class UserPublic(BaseModel):
    id: int = 1
    username: str = "testuser"
    email: str = "test@example.com"
    role: str = "admin"
    is_active: bool = True
```

- [ ] **Step 3: Create `app/api/deps.py`**

```python
"""Stub of BaluHost's app.api.deps. Returns a fixed admin user.

Tests that need a 401 path use FastAPI's ``app.dependency_overrides``
to swap ``get_current_user`` for one that raises ``HTTPException(401)``.
"""
from __future__ import annotations

from app.schemas.user import UserPublic


async def get_current_user() -> UserPublic:
    return UserPublic()
```

- [ ] **Step 4: Verify the stub imports cleanly**

Run:
```bash
cd plugin && python -c "
import sys
sys.path.insert(0, 'tests/fixtures/baluhost_stub')
from app.api.deps import get_current_user
from app.schemas.user import UserPublic
import asyncio
u = asyncio.run(get_current_user())
print(u.username, u.role)
"
```
Expected output: `testuser admin`

- [ ] **Step 5: Commit**

```bash
cd /home/sven/projects/plugins/Balu_Code
git add plugin/tests/fixtures/baluhost_stub/app/schemas/ plugin/tests/fixtures/baluhost_stub/app/api/
git commit -m "test(plugin): extend BaluHost stub with UserPublic and get_current_user"
```

---

## Task 3: `plugin/config.py` — `BaluCodePluginConfig` with 3 Phase-2 fields

**Files:**
- Create: `plugin/tests/test_config.py`
- Create: `plugin/config.py`

- [ ] **Step 1: Write the failing test**

Create `plugin/tests/test_config.py`:

```python
"""Tests for BaluCodePluginConfig."""
from __future__ import annotations

from plugin.config import BaluCodePluginConfig


def test_defaults_are_populated():
    c = BaluCodePluginConfig()
    assert c.ollama_base_url == "http://127.0.0.1:11434"
    assert c.chat_model == "qwen2.5-coder:14b-instruct-q4_K_M"
    assert c.embed_model == "nomic-embed-text"


def test_model_dump_round_trip():
    original = BaluCodePluginConfig(
        ollama_base_url="http://10.0.0.5:11434",
        chat_model="qwen2.5-coder:7b",
        embed_model="nomic-embed-text",
    )
    data = original.model_dump()
    restored = BaluCodePluginConfig.model_validate(data)
    assert restored == original


def test_rejects_unknown_fields():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BaluCodePluginConfig.model_validate(
            {"ollama_base_url": "http://x", "unknown": 1}
        )
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest plugin/tests/test_config.py -v`
Expected: `ModuleNotFoundError: No module named 'plugin.config'`

- [ ] **Step 3: Implement `plugin/config.py`**

```python
"""Plugin-global configuration for balu_code (Phase 2 subset).

Returned by ``BaluCodePlugin.get_config_schema()`` and used by
``BaluCodePlugin.on_startup()`` to construct the OllamaClient and to
report the default chat/embed model when BaluHost serves no per-install
override. Later phases extend this model with RAG/context/iteration
settings.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaluCodePluginConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ollama_base_url: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen2.5-coder:14b-instruct-q4_K_M"
    embed_model: str = "nomic-embed-text"


__all__ = ["BaluCodePluginConfig"]
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest plugin/tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add plugin/config.py plugin/tests/test_config.py
git commit -m "feat(plugin): add BaluCodePluginConfig (ollama_base_url, chat_model, embed_model)"
```

---

## Task 4: `plugin/data_dir.py` — `resolve_data_dir()`

**Files:**
- Create: `plugin/tests/test_data_dir.py`
- Create: `plugin/data_dir.py`

- [ ] **Step 1: Write the failing test**

Create `plugin/tests/test_data_dir.py`:

```python
"""Tests for resolve_data_dir()."""
from __future__ import annotations

from pathlib import Path

from plugin.data_dir import resolve_data_dir


def test_env_var_takes_precedence(tmp_path, monkeypatch):
    target = tmp_path / "balu-code-data"
    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(target))
    result = resolve_data_dir()
    assert result == target
    assert result.is_dir()


def test_fallback_to_xdg_home(tmp_path, monkeypatch):
    monkeypatch.delenv("BALU_CODE_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = resolve_data_dir()
    assert result == tmp_path / ".local" / "share" / "balu-code"
    assert result.is_dir()


def test_idempotent_when_dir_already_exists(tmp_path, monkeypatch):
    target = tmp_path / "existing"
    target.mkdir()
    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(target))
    # Call twice — must not raise, must return same path.
    first = resolve_data_dir()
    second = resolve_data_dir()
    assert first == second == target


def test_creates_nested_missing_dirs(tmp_path, monkeypatch):
    target = tmp_path / "a" / "b" / "c"
    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(target))
    result = resolve_data_dir()
    assert result.is_dir()
    assert result == target


def test_empty_env_var_uses_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("BALU_CODE_DATA_DIR", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    result = resolve_data_dir()
    assert result == tmp_path / ".local" / "share" / "balu-code"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest plugin/tests/test_data_dir.py -v`
Expected: `ModuleNotFoundError: No module named 'plugin.data_dir'`

- [ ] **Step 3: Implement `plugin/data_dir.py`**

```python
"""Resolve and create the balu_code plugin's data directory.

Order of precedence:
1. ``$BALU_CODE_DATA_DIR`` (ops/CI override) — only if non-empty.
2. ``~/.local/share/balu-code/`` (XDG-style default).

The directory is always created (``mkdir(parents=True, exist_ok=True)``)
so callers can assume it exists.
"""
from __future__ import annotations

import os
from pathlib import Path


def resolve_data_dir() -> Path:
    override = os.environ.get("BALU_CODE_DATA_DIR", "").strip()
    if override:
        target = Path(override).expanduser()
    else:
        target = Path.home() / ".local" / "share" / "balu-code"
    target.mkdir(parents=True, exist_ok=True)
    return target


__all__ = ["resolve_data_dir"]
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest plugin/tests/test_data_dir.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add plugin/data_dir.py plugin/tests/test_data_dir.py
git commit -m "feat(plugin): add resolve_data_dir() (BALU_CODE_DATA_DIR env, XDG fallback)"
```

---

## Task 5: `plugin/services/project_store.py` — schema + CRUD

**Files:**
- Create: `plugin/services/__init__.py` (empty)
- Create: `plugin/tests/test_project_store.py`
- Create: `plugin/services/project_store.py`

- [ ] **Step 1: Create `plugin/services/__init__.py`**

```bash
touch plugin/services/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `plugin/tests/test_project_store.py`:

```python
"""Tests for ProjectStore."""
from __future__ import annotations

import pytest

from plugin.services.project_store import (
    DuplicateProjectError,
    Project,
    ProjectNotFoundError,
    ProjectStore,
)


@pytest.fixture
def store(tmp_path):
    s = ProjectStore(tmp_path / "store.db")
    yield s
    s.close()


def test_init_schema_is_idempotent(tmp_path):
    s1 = ProjectStore(tmp_path / "store.db")
    s1.close()
    # Re-open same file: must not raise, must preserve data.
    s2 = ProjectStore(tmp_path / "store.db")
    assert s2.list_projects() == []
    s2.close()


def test_create_and_get_project(store):
    p = store.create_project(name="baluhost", root_path="/home/sven/code/bh", config_yaml=None)
    assert isinstance(p, Project)
    assert p.id > 0
    assert p.name == "baluhost"
    assert p.root_path == "/home/sven/code/bh"
    assert p.config_yaml is None
    assert p.created_at == p.updated_at
    fetched = store.get_project(p.id)
    assert fetched == p


def test_create_project_with_config_yaml(store):
    yaml_blob = "project:\n  name: x\n"
    p = store.create_project(name="x", root_path="/tmp/x", config_yaml=yaml_blob)
    assert p.config_yaml == yaml_blob


def test_list_projects_returns_all(store):
    a = store.create_project(name="a", root_path="/a", config_yaml=None)
    b = store.create_project(name="b", root_path="/b", config_yaml=None)
    result = store.list_projects()
    ids = [p.id for p in result]
    assert a.id in ids
    assert b.id in ids
    assert len(result) == 2


def test_duplicate_name_raises(store):
    store.create_project(name="dup", root_path="/a", config_yaml=None)
    with pytest.raises(DuplicateProjectError):
        store.create_project(name="dup", root_path="/b", config_yaml=None)


def test_get_missing_project_raises(store):
    with pytest.raises(ProjectNotFoundError):
        store.get_project(9999)


def test_delete_removes_project(store):
    p = store.create_project(name="todelete", root_path="/x", config_yaml=None)
    store.delete_project(p.id)
    with pytest.raises(ProjectNotFoundError):
        store.get_project(p.id)
    assert store.list_projects() == []


def test_delete_missing_raises(store):
    with pytest.raises(ProjectNotFoundError):
        store.delete_project(9999)


def test_repo_map_cache_table_exists(store):
    # Phase 2 creates the table but does not populate it.
    conn = store._conn  # internal, but test covers schema contract
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='repo_map_cache'"
    ).fetchone()
    assert row is not None
```

- [ ] **Step 3: Run the test and verify it fails**

Run: `pytest plugin/tests/test_project_store.py -v`
Expected: `ModuleNotFoundError: No module named 'plugin.services.project_store'`

- [ ] **Step 4: Implement `plugin/services/project_store.py`**

```python
"""SQLite-backed project registry for balu_code.

Owns two tables:
- ``projects`` — registered projects (written in Phase 2).
- ``repo_map_cache`` — tree-sitter snapshot cache (schema only in
  Phase 2; rows land in Phase 3).

Uses synchronous ``sqlite3`` with an internal lock. Async callers
should invoke methods via ``asyncio.to_thread``.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel


class ProjectStoreError(Exception):
    """Base for project_store errors."""


class DuplicateProjectError(ProjectStoreError):
    """Raised when a project name is already taken."""


class ProjectNotFoundError(ProjectStoreError):
    """Raised when no project row matches the requested id."""


class Project(BaseModel):
    id: int
    name: str
    root_path: str
    config_yaml: str | None
    created_at: str
    updated_at: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    root_path   TEXT    NOT NULL,
    config_yaml TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS repo_map_cache (
    project_id   INTEGER NOT NULL,
    file_path    TEXT    NOT NULL,
    mtime        REAL    NOT NULL,
    sha1         TEXT    NOT NULL,
    symbols_json TEXT    NOT NULL,
    PRIMARY KEY (project_id, file_path),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProjectStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def create_project(
        self, name: str, root_path: str, config_yaml: str | None
    ) -> Project:
        now = _now_iso()
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO projects (name, root_path, config_yaml, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (name, root_path, config_yaml, now, now),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise DuplicateProjectError(name) from exc
                raise
        project_id = cur.lastrowid
        return Project(
            id=project_id,
            name=name,
            root_path=root_path,
            config_yaml=config_yaml,
            created_at=now,
            updated_at=now,
        )

    def list_projects(self) -> list[Project]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, root_path, config_yaml, created_at, updated_at "
                "FROM projects ORDER BY id ASC"
            ).fetchall()
        return [Project(**dict(r)) for r in rows]

    def get_project(self, project_id: int) -> Project:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, name, root_path, config_yaml, created_at, updated_at "
                "FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            raise ProjectNotFoundError(project_id)
        return Project(**dict(row))

    def delete_project(self, project_id: int) -> None:
        with self._lock:
            cur = self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            self._conn.commit()
        if cur.rowcount == 0:
            raise ProjectNotFoundError(project_id)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = [
    "DuplicateProjectError",
    "Project",
    "ProjectNotFoundError",
    "ProjectStore",
    "ProjectStoreError",
]
```

- [ ] **Step 5: Run the test and verify it passes**

Run: `pytest plugin/tests/test_project_store.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
git add plugin/services/__init__.py plugin/services/project_store.py plugin/tests/test_project_store.py
git commit -m "feat(plugin): add ProjectStore with projects + repo_map_cache schema"
```

---

## Task 6: `OllamaClient.list_models()` — model class + GET /api/tags

**Files:**
- Create: `plugin/tests/test_ollama_client_list_models.py`
- Create: `plugin/services/ollama_client.py` (initial version: errors, OllamaModel, list_models)

- [ ] **Step 1: Write the failing test**

Create `plugin/tests/test_ollama_client_list_models.py`:

```python
"""Tests for OllamaClient.list_models()."""
from __future__ import annotations

import json

import httpx
import pytest

from plugin.services.ollama_client import (
    OllamaClient,
    OllamaModel,
    OllamaUnreachable,
)


def _mock_transport(status: int, body: dict | bytes | Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, Exception):
            raise body
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_list_models_parses_tags_response():
    tags_body = {
        "models": [
            {
                "name": "qwen2.5-coder:14b-instruct-q4_K_M",
                "size": 9100000000,
                "digest": "abc123",
                "modified_at": "2026-04-01T10:00:00Z",
                "details": {"quantization_level": "Q4_K_M"},
            },
            {
                "name": "nomic-embed-text",
                "size": 300000000,
                "digest": "def456",
                "modified_at": "2026-04-02T10:00:00Z",
                "details": {},
            },
        ]
    }
    client = OllamaClient(
        base_url="http://fake:11434", transport=_mock_transport(200, tags_body)
    )
    try:
        models = await client.list_models()
    finally:
        await client.close()

    assert len(models) == 2
    assert isinstance(models[0], OllamaModel)
    assert models[0].name == "qwen2.5-coder:14b-instruct-q4_K_M"
    assert models[0].size == 9100000000
    assert models[0].quantization == "Q4_K_M"
    assert models[1].quantization is None


@pytest.mark.asyncio
async def test_list_models_retries_once_on_connect_error():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"models": []})

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        result = await client.list_models()
    finally:
        await client.close()
    assert result == []
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_list_models_raises_unreachable_after_retries():
    client = OllamaClient(
        base_url="http://fake",
        transport=_mock_transport(0, httpx.ConnectError("down")),
    )
    try:
        with pytest.raises(OllamaUnreachable):
            await client.list_models()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_list_models_invalid_json_raises_unreachable():
    client = OllamaClient(
        base_url="http://fake", transport=_mock_transport(200, b"not-json")
    )
    try:
        with pytest.raises(OllamaUnreachable):
            await client.list_models()
    finally:
        await client.close()
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest plugin/tests/test_ollama_client_list_models.py -v`
Expected: `ModuleNotFoundError: No module named 'plugin.services.ollama_client'`

- [ ] **Step 3: Implement `plugin/services/ollama_client.py`** (first cut — list_models only)

```python
"""Async HTTP client for a local Ollama instance.

Phase 2 surface: ``list_models``. ``embed`` and ``chat_stream`` arrive
in Tasks 7 and 8.

Error hierarchy:
    OllamaError
    ├── OllamaUnreachable     — connection refused / DNS / invalid JSON / repeated 5xx
    ├── OllamaTimeoutError    — httpx.TimeoutException
    └── OllamaRateLimited     — HTTP 429 (surfaces immediately, no retry)

Transport injection: callers MAY pass a custom ``httpx.AsyncBaseTransport``
for tests (``httpx.MockTransport``). Production omits the argument.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from pydantic import BaseModel


class OllamaError(Exception):
    """Base for all Ollama client errors."""


class OllamaUnreachable(OllamaError):
    """Ollama could not be reached (network, DNS, repeated 5xx, invalid JSON)."""


class OllamaTimeoutError(OllamaError):
    """Request to Ollama timed out."""


class OllamaRateLimited(OllamaError):
    """Ollama returned HTTP 429."""


class OllamaModel(BaseModel):
    name: str
    size: int
    digest: str
    quantization: str | None = None
    modified_at: str | None = None


_RETRY_DELAYS = (0.5, 1.5)  # seconds between attempts on transient errors


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
    ) -> httpx.Response:
        """Issue a non-streaming request with one retry on transient errors.

        Retries: ConnectError, ReadError, HTTP 503.
        Immediate: 429 → OllamaRateLimited; TimeoutException → OllamaTimeoutError.
        After the final failed attempt: OllamaUnreachable.
        """
        last_exc: Exception | None = None
        for attempt, delay_before in enumerate((0.0, *_RETRY_DELAYS)):
            if delay_before:
                await asyncio.sleep(delay_before)
            try:
                response = await self._client.request(method, path, json=json_body)
            except httpx.TimeoutException as exc:
                raise OllamaTimeoutError(str(exc)) from exc
            except (httpx.ConnectError, httpx.ReadError) as exc:
                last_exc = exc
                continue
            if response.status_code == 429:
                raise OllamaRateLimited(response.text)
            if response.status_code == 503:
                last_exc = Exception(f"503 {response.text}")
                continue
            if response.status_code >= 500:
                raise OllamaUnreachable(f"HTTP {response.status_code}: {response.text}")
            return response
        raise OllamaUnreachable(f"after {attempt + 1} attempts: {last_exc}")

    async def list_models(self) -> list[OllamaModel]:
        response = await self._request_with_retry("GET", "/api/tags")
        try:
            payload: Any = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise OllamaUnreachable(f"invalid JSON from /api/tags: {exc}") from exc
        result = []
        for entry in payload.get("models", []):
            result.append(
                OllamaModel(
                    name=entry["name"],
                    size=entry["size"],
                    digest=entry["digest"],
                    quantization=(entry.get("details") or {}).get("quantization_level"),
                    modified_at=entry.get("modified_at"),
                )
            )
        return result


__all__ = [
    "OllamaClient",
    "OllamaError",
    "OllamaModel",
    "OllamaRateLimited",
    "OllamaTimeoutError",
    "OllamaUnreachable",
]
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest plugin/tests/test_ollama_client_list_models.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add plugin/services/ollama_client.py plugin/tests/test_ollama_client_list_models.py
git commit -m "feat(plugin): add OllamaClient.list_models with error hierarchy and retry"
```

---

## Task 7: `OllamaClient.embed()`

**Files:**
- Create: `plugin/tests/test_ollama_client_embed.py`
- Modify: `plugin/services/ollama_client.py` (add `embed` method)

Ollama's `/api/embeddings` endpoint takes `{model, prompt}` and returns `{embedding: [float]}`. There is no built-in batch endpoint in Ollama 0.3.x, so `embed(texts)` sequences requests. Later phases may switch to `/api/embed` (newer batched endpoint) once we pin a minimum Ollama version.

- [ ] **Step 1: Write the failing test**

Create `plugin/tests/test_ollama_client_embed.py`:

```python
"""Tests for OllamaClient.embed()."""
from __future__ import annotations

import httpx
import pytest

from plugin.services.ollama_client import OllamaClient, OllamaTimeoutError


@pytest.mark.asyncio
async def test_embed_single_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embeddings"
        body = request.read()
        import json as _json

        data = _json.loads(body)
        assert data["model"] == "nomic-embed-text"
        assert data["prompt"] == "hello"
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        result = await client.embed("nomic-embed-text", ["hello"])
    finally:
        await client.close()
    assert result == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_embed_multiple_texts():
    prompts_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        data = _json.loads(request.read())
        prompts_seen.append(data["prompt"])
        return httpx.Response(200, json={"embedding": [float(len(data["prompt"]))]})

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        result = await client.embed("nomic-embed-text", ["a", "bb", "ccc"])
    finally:
        await client.close()
    assert result == [[1.0], [2.0], [3.0]]
    assert prompts_seen == ["a", "bb", "ccc"]


@pytest.mark.asyncio
async def test_embed_empty_list_returns_empty():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"embedding": []})

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        result = await client.embed("nomic-embed-text", [])
    finally:
        await client.close()
    assert result == []
    assert called is False


@pytest.mark.asyncio
async def test_embed_timeout_mapped():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OllamaTimeoutError):
            await client.embed("m", ["x"])
    finally:
        await client.close()
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest plugin/tests/test_ollama_client_embed.py -v`
Expected: `AttributeError: 'OllamaClient' object has no attribute 'embed'`

- [ ] **Step 3: Add `embed` method to `plugin/services/ollama_client.py`**

Append this method to the `OllamaClient` class (insert after `list_models`):

```python
    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Embed one or more texts via Ollama /api/embeddings.

        Empty input returns ``[]`` without touching the network.
        """
        if not texts:
            return []
        vectors: list[list[float]] = []
        for text in texts:
            response = await self._request_with_retry(
                "POST", "/api/embeddings", json_body={"model": model, "prompt": text}
            )
            try:
                payload = response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise OllamaUnreachable(
                    f"invalid JSON from /api/embeddings: {exc}"
                ) from exc
            vectors.append(list(payload["embedding"]))
        return vectors
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest plugin/tests/test_ollama_client_embed.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add plugin/services/ollama_client.py plugin/tests/test_ollama_client_embed.py
git commit -m "feat(plugin): add OllamaClient.embed (sequential single-prompt embeddings)"
```

---

## Task 8: `OllamaClient.chat_stream()`

**Files:**
- Create: `plugin/tests/test_ollama_client_chat_stream.py`
- Modify: `plugin/services/ollama_client.py` (add `chat_stream` async iterator)

Ollama `/api/chat` returns NDJSON (one JSON object per line), each with a partial `message.content` and a `done` flag. Phase 2 only needs the parser; the agent loop that consumes these frames is Phase 4.

- [ ] **Step 1: Write the failing test**

Create `plugin/tests/test_ollama_client_chat_stream.py`:

```python
"""Tests for OllamaClient.chat_stream()."""
from __future__ import annotations

import httpx
import pytest

from plugin.services.ollama_client import OllamaClient


def _ndjson(frames: list[dict]) -> bytes:
    import json as _json

    return ("\n".join(_json.dumps(f) for f in frames) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_chat_stream_yields_parsed_frames():
    frames = [
        {"model": "m", "message": {"role": "assistant", "content": "Hello"}, "done": False},
        {"model": "m", "message": {"role": "assistant", "content": " world"}, "done": False},
        {
            "model": "m",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        import json as _json

        body = _json.loads(request.read())
        assert body["model"] == "qwen2.5-coder:14b"
        assert body["stream"] is True
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(200, content=_ndjson(frames))

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        collected = []
        async for frame in client.chat_stream(
            "qwen2.5-coder:14b",
            messages=[{"role": "user", "content": "hi"}],
        ):
            collected.append(frame)
    finally:
        await client.close()

    assert len(collected) == 3
    assert collected[0]["message"]["content"] == "Hello"
    assert collected[2]["done"] is True
    assert collected[2]["done_reason"] == "stop"


@pytest.mark.asyncio
async def test_chat_stream_forwards_tools_and_options():
    captured_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured_body.update(_json.loads(request.read()))
        return httpx.Response(200, content=_ndjson([{"done": True}]))

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        async for _ in client.chat_stream(
            "m",
            messages=[{"role": "user", "content": "x"}],
            tools=[{"type": "function", "function": {"name": "read_file"}}],
            options={"temperature": 0.2},
        ):
            pass
    finally:
        await client.close()

    assert captured_body["tools"][0]["function"]["name"] == "read_file"
    assert captured_body["options"] == {"temperature": 0.2}


@pytest.mark.asyncio
async def test_chat_stream_skips_blank_lines():
    body = b'{"message": {"content": "a"}, "done": false}\n\n{"done": true}\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    client = OllamaClient(base_url="http://fake", transport=httpx.MockTransport(handler))
    try:
        collected = []
        async for frame in client.chat_stream("m", messages=[{"role": "user", "content": "x"}]):
            collected.append(frame)
    finally:
        await client.close()
    assert len(collected) == 2
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest plugin/tests/test_ollama_client_chat_stream.py -v`
Expected: `AttributeError: 'OllamaClient' object has no attribute 'chat_stream'`

- [ ] **Step 3: Add `chat_stream` method to `plugin/services/ollama_client.py`**

Append after `embed`:

```python
    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
    ):
        """Stream parsed NDJSON frames from /api/chat.

        Yields each frame as a dict (the raw Ollama envelope). Downstream
        callers decide which keys matter; Phase 2 does not interpret
        ``message.content`` or tool calls.

        Does not apply the retry/backoff logic used by ``_request_with_retry``:
        a stream that dies mid-way leaves the agent loop to decide whether
        to resume, so wrapping it in transparent retries would hide state.
        """
        body: dict = {"model": model, "messages": messages, "stream": True}
        if tools is not None:
            body["tools"] = tools
        if options is not None:
            body["options"] = options

        try:
            async with self._client.stream("POST", "/api/chat", json=body) as response:
                if response.status_code == 429:
                    raise OllamaRateLimited(await response.aread())
                if response.status_code >= 500:
                    raise OllamaUnreachable(
                        f"HTTP {response.status_code} from /api/chat"
                    )
                async for line in response.aiter_lines():
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        yield json.loads(stripped)
                    except (json.JSONDecodeError, ValueError) as exc:
                        raise OllamaUnreachable(
                            f"invalid JSON line from /api/chat: {exc}"
                        ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(str(exc)) from exc
        except (httpx.ConnectError, httpx.ReadError) as exc:
            raise OllamaUnreachable(str(exc)) from exc
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest plugin/tests/test_ollama_client_chat_stream.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add plugin/services/ollama_client.py plugin/tests/test_ollama_client_chat_stream.py
git commit -m "feat(plugin): add OllamaClient.chat_stream (NDJSON async iterator)"
```

---

## Task 9: `plugin/deps.py` + plugin lifecycle (`on_startup`, `on_shutdown`, config hooks)

**Files:**
- Create: `plugin/deps.py`
- Create: `plugin/tests/test_plugin_lifecycle.py`
- Modify: `plugin/__init__.py`

- [ ] **Step 1: Create `plugin/deps.py`**

```python
"""Module-level singletons for the balu_code plugin.

``BaluCodePlugin.on_startup`` constructs the ProjectStore and OllamaClient
and registers them here via ``set_singletons``. Route handlers depend on
the ``get_*`` accessors so tests can override them with
``app.dependency_overrides``.
"""
from __future__ import annotations

from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore

_store: ProjectStore | None = None
_ollama: OllamaClient | None = None


def set_singletons(store: ProjectStore, ollama: OllamaClient) -> None:
    global _store, _ollama
    _store = store
    _ollama = ollama


def clear_singletons() -> None:
    global _store, _ollama
    _store = None
    _ollama = None


def get_project_store() -> ProjectStore:
    if _store is None:
        raise RuntimeError("balu_code plugin not initialized (ProjectStore missing)")
    return _store


def get_ollama_client() -> OllamaClient:
    if _ollama is None:
        raise RuntimeError("balu_code plugin not initialized (OllamaClient missing)")
    return _ollama


__all__ = [
    "clear_singletons",
    "get_ollama_client",
    "get_project_store",
    "set_singletons",
]
```

- [ ] **Step 2: Write the failing test**

Create `plugin/tests/test_plugin_lifecycle.py`:

```python
"""Tests for BaluCodePlugin lifecycle + config hooks."""
from __future__ import annotations

import pytest

from plugin import BaluCodePlugin
from plugin.config import BaluCodePluginConfig
from plugin.deps import (
    clear_singletons,
    get_ollama_client,
    get_project_store,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    clear_singletons()
    yield
    clear_singletons()


def test_get_config_schema_returns_pydantic_model():
    p = BaluCodePlugin()
    assert p.get_config_schema() is BaluCodePluginConfig


def test_get_default_config_matches_defaults():
    p = BaluCodePlugin()
    defaults = p.get_default_config()
    expected = BaluCodePluginConfig().model_dump()
    assert defaults == expected


def test_deps_raise_before_startup():
    with pytest.raises(RuntimeError):
        get_project_store()
    with pytest.raises(RuntimeError):
        get_ollama_client()


@pytest.mark.asyncio
async def test_startup_registers_singletons(tmp_path, monkeypatch):
    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    p = BaluCodePlugin()
    await p.on_startup()
    try:
        store = get_project_store()
        ollama = get_ollama_client()
        assert store.list_projects() == []
        assert (tmp_path / "store.db").exists()
        assert ollama._base_url == "http://127.0.0.1:11434"
    finally:
        await p.on_shutdown()


@pytest.mark.asyncio
async def test_shutdown_clears_singletons(tmp_path, monkeypatch):
    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    p = BaluCodePlugin()
    await p.on_startup()
    await p.on_shutdown()
    with pytest.raises(RuntimeError):
        get_project_store()
    with pytest.raises(RuntimeError):
        get_ollama_client()
```

- [ ] **Step 3: Run the test and verify it fails**

Run: `pytest plugin/tests/test_plugin_lifecycle.py -v`
Expected: multiple failures (attributes missing on BaluCodePlugin).

- [ ] **Step 4: Update `plugin/__init__.py`** to add lifecycle hooks and config schema

Replace the current file with:

```python
"""Balu Code BaluHost plugin.

Loaded at BaluHost startup by PluginManager. Exposes a FastAPI router at
/api/plugins/balu_code/ (currently /health plus project and model routes).
Owns two singletons: a SQLite-backed ProjectStore and an async OllamaClient.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.plugins.base import PluginBase, PluginMetadata
from fastapi import APIRouter

from plugin.config import BaluCodePluginConfig
from plugin.data_dir import resolve_data_dir
from plugin.deps import clear_singletons, set_singletons
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


def _build_router() -> APIRouter:
    """Build the FastAPI router served under /api/plugins/balu_code.

    Routes land in later tasks; Phase 2 keeps only /health until Task 10.
    """
    router = APIRouter()

    @router.get("/health", tags=["balu_code"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "plugin": _MANIFEST["name"],
            "version": _MANIFEST["version"],
        }

    return router


class BaluCodePlugin(PluginBase):
    """Main plugin class. Metadata read from plugin.json at import time."""

    def __init__(self) -> None:
        self._config = BaluCodePluginConfig()
        self._store: ProjectStore | None = None
        self._ollama: OllamaClient | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=_MANIFEST["name"],
            version=_MANIFEST["version"],
            display_name=_MANIFEST["display_name"],
            description=_MANIFEST["description"],
            author=_MANIFEST["author"],
            required_permissions=list(_MANIFEST["required_permissions"]),
            category=_MANIFEST.get("category", "general"),
            homepage=_MANIFEST.get("homepage"),
            min_baluhost_version=_MANIFEST.get("min_baluhost_version"),
            dependencies=list(_MANIFEST.get("plugin_dependencies", [])),
        )

    def get_router(self) -> APIRouter:
        return _build_router()

    def get_config_schema(self) -> type:
        return BaluCodePluginConfig

    def get_default_config(self) -> dict:
        return BaluCodePluginConfig().model_dump()

    async def on_startup(self) -> None:
        data_dir = resolve_data_dir()
        self._store = ProjectStore(data_dir / "store.db")
        self._ollama = OllamaClient(base_url=self._config.ollama_base_url)
        set_singletons(self._store, self._ollama)

    async def on_shutdown(self) -> None:
        if self._ollama is not None:
            await self._ollama.close()
        if self._store is not None:
            self._store.close()
        clear_singletons()
        self._store = None
        self._ollama = None


__all__ = ["BaluCodePlugin"]
```

- [ ] **Step 5: Run the lifecycle tests and verify they pass**

Run: `pytest plugin/tests/test_plugin_lifecycle.py -v`
Expected: 5 passed

- [ ] **Step 6: Run the full plugin test suite to make sure metadata + health still work**

Run: `pytest plugin/tests -v`
Expected: all previous tests + the new 5 still pass.

- [ ] **Step 7: Commit**

```bash
git add plugin/deps.py plugin/__init__.py plugin/tests/test_plugin_lifecycle.py
git commit -m "feat(plugin): wire BaluCodePlugin lifecycle (on_startup/on_shutdown, config hooks, deps singletons)"
```

---

## Task 10: `POST /projects` + `GET /projects` routes

**Files:**
- Create: `plugin/tests/test_routes_phase2.py`
- Modify: `plugin/__init__.py` (extend `_build_router`)

- [ ] **Step 1: Write the failing test**

Create `plugin/tests/test_routes_phase2.py`:

```python
"""Tests for the Phase 2 REST routes."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user

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
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest plugin/tests/test_routes_phase2.py -v`
Expected: fails with 404 or ImportError on schemas — routes not defined yet.

- [ ] **Step 3: Replace `plugin/__init__.py` top-level imports and `_build_router`**

Rewrite the top of the file — replace the current import block (everything from `from __future__` through the `_MANIFEST = ...` line) with the block below. The `BaluCodePlugin` class at the bottom of the file stays exactly as written in Task 9.

```python
"""Balu Code BaluHost plugin.

Loaded at BaluHost startup by PluginManager. Exposes a FastAPI router at
/api/plugins/balu_code/ (currently /health plus project and model routes).
Owns two singletons: a SQLite-backed ProjectStore and an async OllamaClient.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.api.deps import get_current_user
from app.plugins.base import PluginBase, PluginMetadata
from app.schemas.user import UserPublic
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from plugin.config import BaluCodePluginConfig
from plugin.data_dir import resolve_data_dir
from plugin.deps import (
    clear_singletons,
    get_ollama_client,
    get_project_store,
    set_singletons,
)
from plugin.services.ollama_client import OllamaClient, OllamaUnreachable
from plugin.services.project_store import (
    DuplicateProjectError,
    Project,
    ProjectNotFoundError,
    ProjectStore,
)

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    root_path: str = Field(..., min_length=1)
    config_yaml: str | None = None


class ProjectsResponse(BaseModel):
    projects: list[Project]


def _build_router() -> APIRouter:
    """Build the FastAPI router served under /api/plugins/balu_code."""
    router = APIRouter()

    @router.get("/health", tags=["balu_code"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "plugin": _MANIFEST["name"],
            "version": _MANIFEST["version"],
        }

    @router.post(
        "/projects",
        response_model=Project,
        status_code=status.HTTP_201_CREATED,
        tags=["balu_code"],
    )
    async def create_project(
        body: ProjectCreate,
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
    ) -> Project:
        if not os.path.isabs(body.root_path):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="root_path must be absolute",
            )
        try:
            return await asyncio.to_thread(
                store.create_project, body.name, body.root_path, body.config_yaml
            )
        except DuplicateProjectError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"project '{body.name}' already exists",
            ) from exc

    @router.get("/projects", response_model=ProjectsResponse, tags=["balu_code"])
    async def list_projects(
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
    ) -> ProjectsResponse:
        projects = await asyncio.to_thread(store.list_projects)
        return ProjectsResponse(projects=projects)

    return router
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest plugin/tests/test_routes_phase2.py -v`
Expected: 6 passed

- [ ] **Step 5: Run the full plugin suite**

Run: `pytest plugin/tests -v`
Expected: every plugin test still green.

- [ ] **Step 6: Commit**

```bash
git add plugin/__init__.py plugin/tests/test_routes_phase2.py
git commit -m "feat(plugin): add POST /projects and GET /projects routes"
```

---

## Task 11: `GET /projects/{id}` + `DELETE /projects/{id}`

**Files:**
- Modify: `plugin/tests/test_routes_phase2.py` (add tests)
- Modify: `plugin/__init__.py` (add handlers)

- [ ] **Step 1: Append tests to `plugin/tests/test_routes_phase2.py`**

Append these test functions at the end of the file:

```python
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
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run: `pytest plugin/tests/test_routes_phase2.py -v -k "test_get_project_by_id or test_get_project_404 or test_delete_project"`
Expected: 4 failures (405 Method Not Allowed for DELETE, 404 for GET by id since the route pattern isn't defined).

- [ ] **Step 3: Extend `_build_router` in `plugin/__init__.py`**

Inside `_build_router`, before the final `return router`, add:

```python
    @router.get("/projects/{project_id}", response_model=Project, tags=["balu_code"])
    async def get_project(
        project_id: int,
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
    ) -> Project:
        try:
            return await asyncio.to_thread(store.get_project, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"project {project_id} not found",
            ) from exc

    @router.delete(
        "/projects/{project_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["balu_code"],
    )
    async def delete_project(
        project_id: int,
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
    ) -> None:
        try:
            await asyncio.to_thread(store.delete_project, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"project {project_id} not found",
            ) from exc
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest plugin/tests/test_routes_phase2.py -v`
Expected: 10 passed (6 from Task 10 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add plugin/__init__.py plugin/tests/test_routes_phase2.py
git commit -m "feat(plugin): add GET /projects/{id} and DELETE /projects/{id} routes"
```

---

## Task 12: `GET /models` route

**Files:**
- Modify: `plugin/tests/test_routes_phase2.py`
- Modify: `plugin/__init__.py`

- [ ] **Step 1: Append tests to `plugin/tests/test_routes_phase2.py`**

Append at the end of the file:

```python
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
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run: `pytest plugin/tests/test_routes_phase2.py -v -k "models"`
Expected: 2 failures (404 Not Found; route not defined).

- [ ] **Step 3: Extend `_build_router` in `plugin/__init__.py`**

No new top-level imports are needed (all required names are already imported in Task 10's rewrite).

Inside `_build_router`, before `return router`, add:

```python
    @router.get(
        "/models",
        response_model=dict,
        tags=["balu_code"],
    )
    async def list_models_route(
        _user: UserPublic = Depends(get_current_user),
        ollama: OllamaClient = Depends(get_ollama_client),
    ) -> dict:
        try:
            models = await ollama.list_models()
        except OllamaUnreachable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"ollama unreachable: {exc}",
            ) from exc
        return {"models": [m.model_dump() for m in models]}
```

(The handler is named `list_models_route` to avoid shadowing `OllamaClient.list_models`.)

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest plugin/tests/test_routes_phase2.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add plugin/__init__.py plugin/tests/test_routes_phase2.py
git commit -m "feat(plugin): add GET /models route (503 when Ollama unreachable)"
```

---

## Task 13: Auth 401 smoke test

**Files:**
- Modify: `plugin/tests/test_routes_phase2.py`

- [ ] **Step 1: Append test at the end of `plugin/tests/test_routes_phase2.py`**

```python
def test_routes_return_401_when_auth_fails(store):
    from fastapi import HTTPException, status as _status

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
    assert c.post(
        "/api/plugins/balu_code/projects",
        json={"name": "x", "root_path": "/a", "config_yaml": None},
    ).status_code == 401
```

- [ ] **Step 2: Run the test and verify it passes**

Run: `pytest plugin/tests/test_routes_phase2.py::test_routes_return_401_when_auth_fails -v`
Expected: 1 passed. (The test asserts that an override that raises 401 is honored — no code changes needed since the `Depends(get_current_user)` is already wired.)

- [ ] **Step 3: Commit**

```bash
git add plugin/tests/test_routes_phase2.py
git commit -m "test(plugin): verify routes return 401 when get_current_user denies"
```

---

## Task 14: Phase 2 end-to-end verification

**Files:**
- Create: `docs/phase-2-verification.md`

- [ ] **Step 1: Run the full local CI equivalent**

Run:
```bash
source .venv/bin/activate
ruff check .
ruff format --check .
pytest -v
rm -rf dist/
python -m scripts.build_bhplugin --repo-root . --dist dist/
python -m scripts.build_wheel --repo-root . --dist dist/
ls dist/
```
Expected:
- ruff: all checks passed, all files formatted
- pytest: **≥65 tests passing** (Phase 1's 34 + ~31 new from Tasks 3–13)
- `dist/` contains `balu_code-0.1.0.bhplugin`, `balu_code-0.1.0.bhplugin.sha256`, `balu_code_cli-0.1.0-py3-none-any.whl`

- [ ] **Step 2: Verify the built `.bhplugin` contains the Phase 2 modules**

Run:
```bash
python -c "
import zipfile
with zipfile.ZipFile('dist/balu_code-0.1.0.bhplugin') as zf:
    names = sorted(zf.namelist())
want = {
    'config.py',
    'data_dir.py',
    'deps.py',
    'services/ollama_client.py',
    'services/project_store.py',
}
missing = want - set(names)
assert not missing, f'missing in .bhplugin: {missing}'
print('ok', len(names), 'files')
"
```
Expected: `ok <N> files` (no assertion failure).

- [ ] **Step 3: Create `docs/phase-2-verification.md`**

```markdown
# Phase 2 verification — 2026-04-18

## Environment (local dev)

- Commit: (fill in with `git rev-parse --short HEAD`)
- Python: 3.13.5 (local venv; CI matrix covers 3.11 & 3.12)

## Automated checks

- [x] `ruff check .` — no findings
- [x] `ruff format --check .` — clean
- [x] `pytest -v` — ≥65 tests passing
- [x] `python -m scripts.build_bhplugin` produces an archive that includes
      `config.py`, `data_dir.py`, `deps.py`, `services/ollama_client.py`,
      `services/project_store.py`, plus the vendored `balu_code_shared/` tree
- [x] `python -m scripts.build_wheel` still produces the CLI wheel
- [ ] GitHub Actions: CI green on `main` (fill in run URL after push)

## Manual checks to run against dev BaluHost

- [ ] Re-sideload the new `.bhplugin` into
      `/opt/baluhost/backend/app/plugins/installed/balu_code/`
- [ ] Restart the BaluHost backend
- [ ] Check the startup log: plugin reports the `resolve_data_dir()` path and
      the ProjectStore opens without errors
- [ ] `GET /api/plugins/balu_code/health` — still 200 ok
- [ ] `POST /api/plugins/balu_code/projects` with `{name: "demo", root_path: "/tmp", config_yaml: null}` → 201
- [ ] `GET /api/plugins/balu_code/projects` → contains "demo"
- [ ] `GET /api/plugins/balu_code/models` → lists whatever Ollama has pulled

## Plan deviations

(fill in any divergences encountered during execution)

## Known issues carried into Phase 3

- `repo_map_cache` table is created but empty until Phase 3 lands the walker.
- `chat_stream` is implemented but has no in-process caller yet; the agent
  loop lands in Phase 4.
- Live `OllamaClient` errors against a real Ollama instance are not exercised
  in the test suite; `MockTransport` covers the parser + retry logic.
```

- [ ] **Step 4: Commit + push**

```bash
git add docs/phase-2-verification.md
git commit -m "docs: add Phase 2 verification checklist"
git push
```

Expected: push succeeds. Watch `gh run list --limit 1` for the CI result; both matrix jobs (py 3.11 + 3.12) should finish green.

---

## Phase 2 Definition of Done

- All 14 tasks complete and pushed to `main`.
- CI green on `main`.
- Full suite **≥65 tests**, all green locally.
- `.bhplugin` archive includes every new plugin-side module.
- `balu-code --version` (Phase 1) still prints `balu-code 0.1.0` (unchanged).

## What comes next (not this plan)

- **Phase 3 — Repo-Map + RAG.** Tree-sitter walker and budget-aware formatter, `sqlite-vec` chunk store populating `repo_map_cache`, `POST /projects/{id}/index`, `GET /projects/{id}/repo_map`. Python/TypeScript/Go fixture projects.
- **Phase 4 — Agent loop + tools + WebSocket `/chat`.** `services/agent_loop.py`, tool registry, v1 tools, `WS /chat` streaming end-to-end.
- **Phase 5 — CLI chat, init, index, auth, models.** Textual TUI, `.balucode.yaml` parser.
