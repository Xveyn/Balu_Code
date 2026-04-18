# Balu Code — Phase 3a: Repo-Map (Python only)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a server-side Tree-sitter walker for Python files that populates the `repo_map_cache` table from Phase 2 and exposes `GET /api/plugins/balu_code/projects/{id}/repo_map` returning a budget-aware Aider-style text rendering.

**Architecture:** A two-step pipeline. `RepoMap.walk_and_cache(project_root)` enumerates `.py` files honoring a hardcoded ignore list; for each file it stat-mtimes, sha-hashes (only when mtime changed), and re-parses (only when sha changed). Per-file results live in `repo_map_cache(project_id, file_path, mtime, sha1, symbols_json)`. `RepoMap.render(files, budget)` joins per-file Aider-style blocks until a `len(text) // 4` token approximation is exhausted. The route dispatches the walk via `asyncio.to_thread` because tree-sitter parsing is CPU-bound. Before any of that, `plugin/__init__.py` (228 LOC) is split into `plugin/schemas.py` + `plugin/routes.py` so the new route lands in a focused file.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, sqlite3, `tree-sitter>=0.22`, `tree-sitter-python>=0.21`, pytest.

**Parent spec:** [`docs/superpowers/specs/2026-04-18-balu-code-phase-3a-repo-map-design.md`](../specs/2026-04-18-balu-code-phase-3a-repo-map-design.md)

---

## File Structure (this phase)

```
Balu_Code/
└── plugin/
    ├── __init__.py                                ← shrunk in Tasks 1+2 (now ~80 LOC)
    ├── schemas.py                                 ← new (Tasks 1, 8)
    ├── routes.py                                  ← new (Task 2, extended in Task 9)
    ├── plugin.json                                ← modified (Task 3)
    ├── requirements.txt                           ← modified (Task 3)
    ├── pyproject.toml                             ← modified (Task 3)
    ├── services/
    │   ├── project_store.py                       ← extended (Task 4)
    │   ├── repo_map.py                            ← new (Tasks 5, 6, 7)
    │   └── repo_map_python.py                     ← new (Task 5)
    └── tests/
        ├── test_project_store.py                  ← extended (Task 4)
        ├── test_repo_map_python.py                ← new (Task 5)
        ├── test_repo_map_walker.py                ← new (Task 6)
        ├── test_repo_map_render.py                ← new (Task 7)
        ├── test_schemas.py                        ← new (Task 8)
        └── test_routes_repo_map.py                ← new (Task 9)
```

Task 10 is verification.

---

## Task 1: Refactor — extract `plugin/schemas.py`

**Files:**
- Create: `plugin/schemas.py`
- Modify: `plugin/__init__.py`

Behaviour-neutral. The full Phase-2 suite (currently 88 passing) must remain at 88 passing throughout. The `BaluCodePlugin` class and `_build_router` stay in `__init__.py` for now — Task 2 moves the router.

- [ ] **Step 1: Create `plugin/schemas.py`**

```python
"""Request/response Pydantic schemas for balu_code routes.

Kept separate from ``plugin/__init__.py`` so the plugin entry module
stays small and so route handlers in ``plugin/routes.py`` can import
schemas without pulling in lifecycle code.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from plugin.services.ollama_client import OllamaModel
from plugin.services.project_store import Project


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    root_path: str = Field(..., min_length=1)
    config_yaml: str | None = None


class ProjectsResponse(BaseModel):
    projects: list[Project]


class ModelsResponse(BaseModel):
    models: list[OllamaModel]


__all__ = [
    "ModelsResponse",
    "ProjectCreate",
    "ProjectsResponse",
]
```

- [ ] **Step 2: Update `plugin/__init__.py`** to import from `plugin.schemas` instead of defining the three models locally.

Find the existing model definitions in `plugin/__init__.py`:

```python
class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    root_path: str = Field(..., min_length=1)
    config_yaml: str | None = None


class ProjectsResponse(BaseModel):
    projects: list[Project]


class ModelsResponse(BaseModel):
    models: list[OllamaModel]
```

Replace those three class definitions with a single line in the existing imports area:

```python
from plugin.schemas import ModelsResponse, ProjectCreate, ProjectsResponse
```

Remove the now-unused imports `BaseModel, Field` from the `from pydantic import ...` line. (Pydantic was only used to build those three models; the `BaluCodePlugin` class doesn't use it directly.)

Keep `Project, OllamaModel` imports as-is — `routes.py` (still inside `__init__.py` for one more task) still references them.

- [ ] **Step 3: Run the full suite to verify no behaviour change**

```bash
source .venv/bin/activate
ruff check .
ruff format --check .
pytest
```

Expected:
- ruff: all checks passed.
- pytest: **88 passed** (unchanged).

- [ ] **Step 4: Commit**

```bash
git add plugin/__init__.py plugin/schemas.py
git commit -m "refactor(plugin): extract Pydantic schemas to plugin/schemas.py"
```

---

## Task 2: Refactor — extract `plugin/routes.py`

**Files:**
- Create: `plugin/routes.py`
- Modify: `plugin/__init__.py`

- [ ] **Step 1: Create `plugin/routes.py`**

Move the entire `_build_router()` function plus every import line that the handlers (and only the handlers) need. Use the name `build_router` (no underscore prefix) so the plugin's `get_router` can import it cleanly.

```python
"""FastAPI router for the balu_code plugin.

Hosts every route under ``/api/plugins/balu_code/`` minus the prefix.
The route surface is grouped here so adding a new endpoint in later
phases is a single-file change.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.api.deps import get_current_user
from app.schemas.user import UserPublic
from fastapi import APIRouter, Depends, HTTPException, status

from plugin.deps import get_ollama_client, get_project_store
from plugin.schemas import ModelsResponse, ProjectCreate, ProjectsResponse
from plugin.services.ollama_client import (
    OllamaClient,
    OllamaRateLimited,
    OllamaTimeoutError,
    OllamaUnreachable,
)
from plugin.services.project_store import (
    DuplicateProjectError,
    Project,
    ProjectNotFoundError,
    ProjectStore,
)

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


def build_router() -> APIRouter:
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

    @router.get("/models", response_model=ModelsResponse, tags=["balu_code"])
    async def list_models_route(
        _user: UserPublic = Depends(get_current_user),
        ollama: OllamaClient = Depends(get_ollama_client),
    ) -> ModelsResponse:
        try:
            models = await ollama.list_models()
        except OllamaUnreachable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"ollama unreachable: {exc}",
            ) from exc
        except OllamaTimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"ollama timeout: {exc}",
            ) from exc
        except OllamaRateLimited as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"ollama rate-limited: {exc}",
            ) from exc
        return ModelsResponse(models=models)

    return router


__all__ = ["build_router"]
```

- [ ] **Step 2: Replace the contents of `plugin/__init__.py`**

The plugin entry module collapses to just the `BaluCodePlugin` lifecycle class. Replace the whole file with:

```python
"""Balu Code BaluHost plugin.

Loaded at BaluHost startup by PluginManager. Exposes a FastAPI router at
/api/plugins/balu_code/ — see ``plugin/routes.py`` for the route surface.
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
from plugin.routes import build_router
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


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
        return build_router()

    def get_config_schema(self) -> type:
        return BaluCodePluginConfig

    def get_default_config(self) -> dict:
        return BaluCodePluginConfig().model_dump()

    async def on_startup(self) -> None:
        data_dir = resolve_data_dir()
        store = ProjectStore(data_dir / "store.db")
        try:
            ollama = OllamaClient(base_url=self._config.ollama_base_url)
        except BaseException:
            store.close()
            raise
        self._store = store
        self._ollama = ollama
        set_singletons(store, ollama)

    async def on_shutdown(self) -> None:
        if self._store is None and self._ollama is None:
            return
        if self._ollama is not None:
            await self._ollama.close()
        if self._store is not None:
            self._store.close()
        clear_singletons()
        self._store = None
        self._ollama = None


__all__ = ["BaluCodePlugin"]
```

- [ ] **Step 3: Run the full suite — must still be 88 passing**

```bash
ruff check .
ruff format --check .
pytest
```

Expected:
- ruff: all checks passed.
- pytest: **88 passed** (no behaviour change).

If the route tests in `plugin/tests/test_routes_phase2.py` still import any helpers from `plugin/__init__.py` other than `BaluCodePlugin`, that import will break. Tests should only do `from plugin import BaluCodePlugin` and `from plugin.deps import get_project_store, get_ollama_client` and `from app.api.deps import get_current_user` — nothing else from `plugin/__init__.py`. Verify with `grep -n "from plugin import" plugin/tests/`. If any test imports a moved symbol (e.g. `ProjectCreate`), update that test's import to `from plugin.schemas import ProjectCreate`.

- [ ] **Step 4: Commit**

```bash
git add plugin/__init__.py plugin/routes.py
git commit -m "refactor(plugin): extract router factory to plugin/routes.py"
```

---

## Task 3: Add Tree-sitter dependencies

**Files:**
- Modify: `plugin/plugin.json`
- Modify: `plugin/requirements.txt`
- Modify: `plugin/pyproject.toml`

- [ ] **Step 1: Update `plugin/plugin.json`** — add the two new packages to `python_requirements`:

Find the existing block:

```json
  "python_requirements": [
    "httpx>=0.27",
    "pydantic>=2.6"
  ],
```

Replace with:

```json
  "python_requirements": [
    "httpx>=0.27",
    "pydantic>=2.6",
    "tree-sitter>=0.22",
    "tree-sitter-python>=0.21"
  ],
```

- [ ] **Step 2: Update `plugin/requirements.txt`** — append:

```
tree-sitter>=0.22
tree-sitter-python>=0.21
```

The full file becomes:

```
httpx>=0.27
pydantic>=2.6
tree-sitter>=0.22
tree-sitter-python>=0.21
```

- [ ] **Step 3: Update `plugin/pyproject.toml`** — add the two packages to `[project] dependencies`:

Find the existing block:

```toml
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.6",
  "fastapi>=0.110",
  "balu-code-shared",
]
```

Insert the two packages after `pydantic`:

```toml
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.6",
  "tree-sitter>=0.22",
  "tree-sitter-python>=0.21",
  "fastapi>=0.110",
  "balu-code-shared",
]
```

- [ ] **Step 4: Refresh the dev install**

```bash
source .venv/bin/activate
pip install -e "plugin[dev]"
```

Expected: `pip` installs `tree-sitter` and `tree-sitter-python` (one or both may already be cached). No errors.

- [ ] **Step 5: Smoke-test the import**

```bash
python -c "import tree_sitter; import tree_sitter_python; from tree_sitter import Language, Parser; print('ok', Language(tree_sitter_python.language()).version)"
```

Expected: `ok <int>` (the int is the grammar's ABI version; any positive int is fine).

- [ ] **Step 6: Run the existing suite — no regression**

```bash
ruff check .
ruff format --check .
pytest
```

Expected: 88 passed, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add plugin/plugin.json plugin/requirements.txt plugin/pyproject.toml
git commit -m "build(plugin): add tree-sitter and tree-sitter-python dependencies"
```

---

## Task 4: Extend `ProjectStore` with `repo_map_cache` CRUD

**Files:**
- Modify: `plugin/services/project_store.py`
- Modify: `plugin/tests/test_project_store.py`

The `repo_map_cache` table was created in Phase 2 but only its existence was tested. Phase 3a needs three methods on `ProjectStore` plus a `RepoMapCacheRow` Pydantic model. The walker (Task 6) calls these.

- [ ] **Step 1: Append failing tests to `plugin/tests/test_project_store.py`**

Add these test functions at the end of the file:

```python
def test_upsert_inserts_new_repo_map_entry(store):
    p = store.create_project(name="rm1", root_path="/x", config_yaml=None)
    store.upsert_repo_map_entry(
        project_id=p.id,
        file_path="src/a.py",
        mtime=1700000000.0,
        sha1="aaa",
        symbols_json='{"imports": []}',
    )
    rows = store.list_repo_map_entries(p.id)
    assert len(rows) == 1
    assert rows[0].file_path == "src/a.py"
    assert rows[0].sha1 == "aaa"
    assert rows[0].symbols_json == '{"imports": []}'


def test_upsert_replaces_existing_entry(store):
    p = store.create_project(name="rm2", root_path="/x", config_yaml=None)
    store.upsert_repo_map_entry(p.id, "a.py", 1.0, "sha1_old", '{"v":1}')
    store.upsert_repo_map_entry(p.id, "a.py", 2.0, "sha1_new", '{"v":2}')
    rows = store.list_repo_map_entries(p.id)
    assert len(rows) == 1
    assert rows[0].mtime == 2.0
    assert rows[0].sha1 == "sha1_new"
    assert rows[0].symbols_json == '{"v":2}'


def test_list_repo_map_entries_isolates_by_project(store):
    p1 = store.create_project(name="rm3a", root_path="/x", config_yaml=None)
    p2 = store.create_project(name="rm3b", root_path="/y", config_yaml=None)
    store.upsert_repo_map_entry(p1.id, "p1.py", 1.0, "h1", "{}")
    store.upsert_repo_map_entry(p2.id, "p2.py", 1.0, "h2", "{}")
    rows1 = store.list_repo_map_entries(p1.id)
    rows2 = store.list_repo_map_entries(p2.id)
    assert [r.file_path for r in rows1] == ["p1.py"]
    assert [r.file_path for r in rows2] == ["p2.py"]


def test_delete_repo_map_entries_drops_paths_not_in_keep_set(store):
    p = store.create_project(name="rm4", root_path="/x", config_yaml=None)
    for path in ("keep.py", "drop.py", "also_drop.py"):
        store.upsert_repo_map_entry(p.id, path, 1.0, "h", "{}")
    store.delete_repo_map_entries(p.id, paths_to_keep={"keep.py"})
    remaining = {r.file_path for r in store.list_repo_map_entries(p.id)}
    assert remaining == {"keep.py"}


def test_delete_repo_map_entries_with_empty_keep_set_clears_all(store):
    p = store.create_project(name="rm5", root_path="/x", config_yaml=None)
    store.upsert_repo_map_entry(p.id, "a.py", 1.0, "h", "{}")
    store.delete_repo_map_entries(p.id, paths_to_keep=set())
    assert store.list_repo_map_entries(p.id) == []


def test_deleting_project_cascades_to_repo_map_cache(store):
    p = store.create_project(name="rm6", root_path="/x", config_yaml=None)
    store.upsert_repo_map_entry(p.id, "a.py", 1.0, "h", "{}")
    store.delete_project(p.id)
    # Re-create with the same name — the new project gets a fresh id;
    # the old rows must have cascaded away rather than lingering on the
    # detached project_id.
    p2 = store.create_project(name="rm6", root_path="/x", config_yaml=None)
    assert store.list_repo_map_entries(p2.id) == []
```

- [ ] **Step 2: Run the new tests and verify they fail**

```bash
pytest plugin/tests/test_project_store.py -v -k "upsert or list_repo_map or delete_repo_map or cascade"
```

Expected: 6 failures (`AttributeError: 'ProjectStore' object has no attribute 'upsert_repo_map_entry'` and similar).

- [ ] **Step 3: Add the new model + methods to `plugin/services/project_store.py`**

Inside `plugin/services/project_store.py`, add a new Pydantic class right next to the existing `Project` class:

```python
class RepoMapCacheRow(BaseModel):
    project_id: int
    file_path: str
    mtime: float
    sha1: str
    symbols_json: str
```

Append `RepoMapCacheRow` to the `__all__` list at the bottom of the file (alphabetical order).

Inside the `ProjectStore` class, add three new methods after `delete_project`:

```python
    def upsert_repo_map_entry(
        self,
        project_id: int,
        file_path: str,
        mtime: float,
        sha1: str,
        symbols_json: str,
    ) -> None:
        """Insert or replace a row in repo_map_cache."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO repo_map_cache "
                "(project_id, file_path, mtime, sha1, symbols_json) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(project_id, file_path) DO UPDATE SET "
                "mtime = excluded.mtime, "
                "sha1 = excluded.sha1, "
                "symbols_json = excluded.symbols_json",
                (project_id, file_path, mtime, sha1, symbols_json),
            )
            self._conn.commit()

    def list_repo_map_entries(self, project_id: int) -> list[RepoMapCacheRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT project_id, file_path, mtime, sha1, symbols_json "
                "FROM repo_map_cache WHERE project_id = ? ORDER BY file_path ASC",
                (project_id,),
            ).fetchall()
        return [RepoMapCacheRow(**dict(r)) for r in rows]

    def delete_repo_map_entries(
        self, project_id: int, paths_to_keep: set[str]
    ) -> None:
        """Delete every cached row for ``project_id`` whose file_path is not in ``paths_to_keep``."""
        with self._lock:
            if not paths_to_keep:
                self._conn.execute(
                    "DELETE FROM repo_map_cache WHERE project_id = ?",
                    (project_id,),
                )
            else:
                placeholders = ",".join("?" * len(paths_to_keep))
                params = (project_id, *sorted(paths_to_keep))
                self._conn.execute(
                    f"DELETE FROM repo_map_cache WHERE project_id = ? "  # noqa: S608
                    f"AND file_path NOT IN ({placeholders})",
                    params,
                )
            self._conn.commit()
```

The `# noqa: S608` is for the bandit/ruff "SQL injection" warning — `placeholders` is a string of `?` characters built by us, never user input, so it's safe. (If ruff doesn't flag it on your install, omit the comment.)

- [ ] **Step 4: Run the new tests and verify they pass**

```bash
pytest plugin/tests/test_project_store.py -v
```

Expected: **15 passed** (9 existing + 6 new).

- [ ] **Step 5: Run the full suite + ruff**

```bash
ruff check .
pytest
```

Expected:
- ruff: all checks passed.
- pytest: **94 passed** (88 existing + 6 new).

- [ ] **Step 6: Commit**

```bash
git add plugin/services/project_store.py plugin/tests/test_project_store.py
git commit -m "feat(plugin): add ProjectStore CRUD for repo_map_cache (upsert/list/delete)"
```

---

## Task 5: `repo_map_python.py` — `parse_python_file` + dataclasses in `repo_map.py`

**Files:**
- Create: `plugin/services/repo_map.py` (initial: dataclasses + errors only)
- Create: `plugin/services/repo_map_python.py`
- Create: `plugin/tests/test_repo_map_python.py`

This task introduces the language-agnostic dataclasses and the Python-specific tree-sitter parser. It does NOT yet introduce the `RepoMap` walker (Task 6) or the `render` function (Task 7).

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_repo_map_python.py`:

```python
"""Tests for parse_python_file."""
from __future__ import annotations

from plugin.services.repo_map import ClassSymbol, FunctionSymbol
from plugin.services.repo_map_python import parse_python_file


def test_empty_file_returns_three_empty_lists():
    imports, classes, functions = parse_python_file(b"")
    assert imports == []
    assert classes == []
    assert functions == []


def test_plain_imports():
    src = b"import os\nimport sys, json\n"
    imports, _, _ = parse_python_file(src)
    assert "os" in imports
    assert "sys" in imports
    assert "json" in imports


def test_dotted_import():
    src = b"import xml.etree.ElementTree\n"
    imports, _, _ = parse_python_file(src)
    assert "xml.etree.ElementTree" in imports


def test_aliased_import():
    src = b"import numpy as np\n"
    imports, _, _ = parse_python_file(src)
    assert "numpy" in imports


def test_from_import():
    src = b"from app.models import User, Group\n"
    imports, _, _ = parse_python_file(src)
    assert "app.models" in imports


def test_relative_from_import():
    src = b"from .helpers import x\nfrom ..parent import y\n"
    imports, _, _ = parse_python_file(src)
    assert ".helpers" in imports
    assert "..parent" in imports


def test_multiline_from_import():
    src = b"from app.models import (\n    User,\n    Group,\n)\n"
    imports, _, _ = parse_python_file(src)
    assert "app.models" in imports


def test_top_level_function():
    src = b"def foo(x: int) -> str:\n    return str(x)\n"
    _, _, functions = parse_python_file(src)
    assert len(functions) == 1
    assert functions[0].name == "foo"
    assert functions[0].signature == "def foo(x: int) -> str"


def test_async_function():
    src = b"async def fetch(url: str) -> bytes:\n    return b''\n"
    _, _, functions = parse_python_file(src)
    assert len(functions) == 1
    assert functions[0].name == "fetch"
    assert functions[0].signature.startswith("async def fetch(")
    assert functions[0].signature.endswith(" -> bytes")


def test_decorated_function_is_recorded():
    src = b"import functools\n@functools.cache\ndef cached() -> int:\n    return 1\n"
    _, _, functions = parse_python_file(src)
    assert any(f.name == "cached" for f in functions)


def test_function_without_return_type_omits_arrow():
    src = b"def f(x):\n    pass\n"
    _, _, functions = parse_python_file(src)
    assert functions[0].signature == "def f(x)"


def test_class_with_methods():
    src = (
        b"class Service(Base, IFace):\n"
        b"    def __init__(self, x: int) -> None:\n"
        b"        self.x = x\n"
        b"    async def call(self) -> str:\n"
        b"        return ''\n"
    )
    _, classes, _ = parse_python_file(src)
    assert len(classes) == 1
    cls = classes[0]
    assert cls.name == "Service"
    assert cls.bases == ["Base", "IFace"]
    assert any(m.startswith("def __init__(self, x: int)") for m in cls.methods)
    assert any(m.startswith("async def call(self)") for m in cls.methods)


def test_decorated_class():
    src = (
        b"@register\n"
        b"class Registered:\n"
        b"    def x(self): ...\n"
    )
    _, classes, _ = parse_python_file(src)
    assert len(classes) == 1
    assert classes[0].name == "Registered"


def test_class_without_bases():
    src = b"class Plain:\n    pass\n"
    _, classes, _ = parse_python_file(src)
    assert classes[0].bases == []


def test_syntax_error_returns_three_empty_lists():
    src = b"def broken(\n"  # unterminated
    imports, classes, functions = parse_python_file(src)
    # Tree-sitter is error-tolerant; we may still extract partial results.
    # The contract is "no exception". Accept anything that does not raise.
    assert isinstance(imports, list)
    assert isinstance(classes, list)
    assert isinstance(functions, list)


def test_returns_correct_dataclass_types():
    src = b"def f(): pass\nclass C: pass\n"
    _, classes, functions = parse_python_file(src)
    assert isinstance(functions[0], FunctionSymbol)
    assert isinstance(classes[0], ClassSymbol)
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
pytest plugin/tests/test_repo_map_python.py -v
```

Expected: `ModuleNotFoundError: No module named 'plugin.services.repo_map'`.

- [ ] **Step 3: Create `plugin/services/repo_map.py` with the dataclasses**

```python
"""Domain types and runtime entry point for the repo-map walker.

This module is intentionally language-agnostic. Per-language extractors
live in sibling modules (``repo_map_python.py``, future ``repo_map_ts.py``,
etc.) and return the dataclasses defined here.

Phase 3a ships only the types and the public surface skeleton; the
``RepoMap`` class with ``walk_and_cache`` and ``render`` is added in
Tasks 6 and 7.
"""
from __future__ import annotations

from dataclasses import dataclass


class RepoMapError(Exception):
    """Base class for repo-map errors."""


class ProjectRootNotAccessible(RepoMapError):
    """Raised when the project's root_path does not exist or is not a directory."""


@dataclass(frozen=True)
class ClassSymbol:
    name: str
    bases: list[str]
    methods: list[str]    # rendered method signatures: 'def foo(self, x: int) -> str'


@dataclass(frozen=True)
class FunctionSymbol:
    name: str
    signature: str        # 'def bar(x: int = 1) -> None'


@dataclass(frozen=True)
class FileSymbols:
    path: str             # POSIX-style, relative to project root
    lines: int
    imports: list[str]
    classes: list[ClassSymbol]
    functions: list[FunctionSymbol]


@dataclass(frozen=True)
class RenderedMap:
    text: str
    file_count: int
    truncated_files: list[str]
    total_bytes: int


__all__ = [
    "ClassSymbol",
    "FileSymbols",
    "FunctionSymbol",
    "ProjectRootNotAccessible",
    "RenderedMap",
    "RepoMapError",
]
```

Frozen dataclasses with mutable list defaults work in Python 3.11+ — the lists are passed in, not constructed via field defaults, so `frozen=True` doesn't conflict.

- [ ] **Step 4: Create `plugin/services/repo_map_python.py`**

```python
"""Tree-sitter-backed Python source parser.

Returns the three lists ``RepoMap`` consumes: imports (module names as
written), classes (with bases + method signatures), top-level functions
(with signatures). Decorated definitions are unwrapped — the decorator
itself is not surfaced.

The tree-sitter ``Parser`` is built once per process (lazy) and reused.
"""
from __future__ import annotations

from tree_sitter import Language, Parser
import tree_sitter_python as tsp

from plugin.services.repo_map import ClassSymbol, FunctionSymbol


_parser: Parser | None = None


def _get_parser() -> Parser:
    global _parser
    if _parser is None:
        _parser = Parser(Language(tsp.language()))
    return _parser


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _signature(node, source: bytes) -> str:
    """Build 'def name(params) -> ReturnType' from a function_definition node.

    Handles async-def by checking for an ``async`` token among children.
    """
    name_node = node.child_by_field_name("name")
    params_node = node.child_by_field_name("parameters")
    return_node = node.child_by_field_name("return_type")
    name = _node_text(name_node, source) if name_node else "<anon>"
    params = _node_text(params_node, source) if params_node else "()"
    is_async = any(c.type == "async" for c in node.children)
    prefix = "async def " if is_async else "def "
    sig = f"{prefix}{name}{params}"
    if return_node is not None:
        sig += f" -> {_node_text(return_node, source)}"
    return sig


def _extract_import(node, source: bytes) -> list[str]:
    """Handle 'import X', 'import X.Y', 'import X as Z', 'import X, Y'."""
    out: list[str] = []
    for child in node.children:
        if child.type == "dotted_name":
            out.append(_node_text(child, source))
        elif child.type == "aliased_import":
            inner = child.child_by_field_name("name")
            if inner is not None:
                out.append(_node_text(inner, source))
    return out


def _extract_import_from(node, source: bytes) -> list[str]:
    """Handle 'from X import Y', 'from .X import Y', 'from . import Y'.

    Returns the module name only (one entry per statement).
    """
    module_node = node.child_by_field_name("module_name")
    if module_node is None:
        return []
    return [_node_text(module_node, source)]


def _build_class(node, source: bytes) -> ClassSymbol:
    name_node = node.child_by_field_name("name")
    name = _node_text(name_node, source) if name_node else "<anon>"

    superclasses_node = node.child_by_field_name("superclasses")
    bases: list[str] = []
    if superclasses_node is not None:
        for child in superclasses_node.children:
            if child.type in ("identifier", "attribute"):
                bases.append(_node_text(child, source))

    body_node = node.child_by_field_name("body")
    methods: list[str] = []
    if body_node is not None:
        for child in body_node.children:
            if child.type == "function_definition":
                methods.append(_signature(child, source))
            elif child.type == "decorated_definition":
                inner = child.child_by_field_name("definition")
                if inner is not None and inner.type == "function_definition":
                    methods.append(_signature(inner, source))

    return ClassSymbol(name=name, bases=bases, methods=methods)


def _build_function(node, source: bytes) -> FunctionSymbol:
    name_node = node.child_by_field_name("name")
    name = _node_text(name_node, source) if name_node else "<anon>"
    return FunctionSymbol(name=name, signature=_signature(node, source))


def parse_python_file(
    source: bytes,
) -> tuple[list[str], list[ClassSymbol], list[FunctionSymbol]]:
    """Parse Python source bytes; return (imports, classes, top-level functions).

    Tree-sitter is error-tolerant — partial parses still yield whatever the
    parser successfully recognised. This function never raises on bad input.
    """
    parser = _get_parser()
    try:
        tree = parser.parse(source)
    except Exception:
        return [], [], []

    imports: list[str] = []
    classes: list[ClassSymbol] = []
    functions: list[FunctionSymbol] = []

    for node in tree.root_node.children:
        nt = node.type
        if nt == "import_statement":
            imports.extend(_extract_import(node, source))
        elif nt == "import_from_statement":
            imports.extend(_extract_import_from(node, source))
        elif nt == "class_definition":
            classes.append(_build_class(node, source))
        elif nt == "function_definition":
            functions.append(_build_function(node, source))
        elif nt == "decorated_definition":
            inner = node.child_by_field_name("definition")
            if inner is None:
                continue
            if inner.type == "class_definition":
                classes.append(_build_class(inner, source))
            elif inner.type == "function_definition":
                functions.append(_build_function(inner, source))

    return imports, classes, functions


__all__ = ["parse_python_file"]
```

- [ ] **Step 5: Run the parser tests**

```bash
pytest plugin/tests/test_repo_map_python.py -v
```

Expected: 16 passed.

- [ ] **Step 6: Run the full suite + ruff**

```bash
ruff check .
ruff format --check .
pytest
```

Expected:
- ruff: all checks passed.
- pytest: **110 passed** (94 existing + 16 new).

- [ ] **Step 7: Commit**

```bash
git add plugin/services/repo_map.py plugin/services/repo_map_python.py plugin/tests/test_repo_map_python.py
git commit -m "feat(plugin): add tree-sitter Python parser + repo_map dataclasses"
```

---

## Task 6: `RepoMap.walk_and_cache`

**Files:**
- Modify: `plugin/services/repo_map.py`
- Create: `plugin/tests/test_repo_map_walker.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_repo_map_walker.py`:

```python
"""Tests for RepoMap.walk_and_cache."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plugin.services.project_store import ProjectStore
from plugin.services.repo_map import (
    FileSymbols,
    ProjectRootNotAccessible,
    RepoMap,
)


@pytest.fixture
def store(tmp_path) -> ProjectStore:
    s = ProjectStore(tmp_path / "store.db")
    yield s
    s.close()


@pytest.fixture
def project_id(store) -> int:
    p = store.create_project(name="walker", root_path="/unused", config_yaml=None)
    return p.id


def _write(root: Path, rel: str, content: str) -> Path:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def test_raises_when_root_does_not_exist(tmp_path, store, project_id):
    rm = RepoMap(project_root=tmp_path / "missing", store=store, project_id=project_id)
    with pytest.raises(ProjectRootNotAccessible):
        rm.walk_and_cache()


def test_raises_when_root_is_a_file(tmp_path, store, project_id):
    f = tmp_path / "afile"
    f.write_text("hi")
    rm = RepoMap(project_root=f, store=store, project_id=project_id)
    with pytest.raises(ProjectRootNotAccessible):
        rm.walk_and_cache()


def test_walks_python_files_only(tmp_path, store, project_id):
    _write(tmp_path, "a.py", "def foo(): pass\n")
    _write(tmp_path, "b.txt", "ignored\n")
    _write(tmp_path, "sub/c.py", "def bar(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    files = sorted(rm.walk_and_cache(), key=lambda f: f.path)
    assert [f.path for f in files] == ["a.py", "sub/c.py"]
    assert all(isinstance(f, FileSymbols) for f in files)


def test_skips_ignored_directories(tmp_path, store, project_id):
    _write(tmp_path, "src/keep.py", "def k(): pass\n")
    _write(tmp_path, "__pycache__/ignored.py", "def x(): pass\n")
    _write(tmp_path, ".venv/lib/site-packages/dropped.py", "def y(): pass\n")
    _write(tmp_path, "node_modules/index.py", "def z(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    paths = {f.path for f in rm.walk_and_cache()}
    assert paths == {"src/keep.py"}


def test_second_walk_is_a_cache_hit_for_unchanged_files(
    tmp_path, store, project_id, monkeypatch
):
    _write(tmp_path, "a.py", "def f(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    rm.walk_and_cache()  # populate cache

    parse_calls = []

    def counting_parse(source: bytes):
        parse_calls.append(source)
        from plugin.services.repo_map_python import parse_python_file as real

        return real(source)

    monkeypatch.setattr(
        "plugin.services.repo_map.parse_python_file", counting_parse
    )
    rm2 = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    files = rm2.walk_and_cache()
    assert len(files) == 1
    assert parse_calls == []  # no re-parse on unchanged files


def test_mtime_change_without_content_change_skips_reparse(
    tmp_path, store, project_id, monkeypatch
):
    p = _write(tmp_path, "a.py", "def f(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    rm.walk_and_cache()

    # Touch the file to change mtime but not content.
    import os

    new_mtime = p.stat().st_mtime + 100
    os.utime(p, (new_mtime, new_mtime))

    parse_calls = []

    def counting_parse(source: bytes):
        parse_calls.append(source)
        from plugin.services.repo_map_python import parse_python_file as real

        return real(source)

    monkeypatch.setattr(
        "plugin.services.repo_map.parse_python_file", counting_parse
    )
    rm2 = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    files = rm2.walk_and_cache()
    assert len(files) == 1
    assert parse_calls == []  # mtime drift but sha unchanged → no re-parse


def test_content_change_triggers_reparse(tmp_path, store, project_id, monkeypatch):
    p = _write(tmp_path, "a.py", "def old(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    rm.walk_and_cache()

    p.write_text("def new(): pass\n")

    parse_calls = []

    def counting_parse(source: bytes):
        parse_calls.append(source)
        from plugin.services.repo_map_python import parse_python_file as real

        return real(source)

    monkeypatch.setattr(
        "plugin.services.repo_map.parse_python_file", counting_parse
    )
    rm2 = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    files = rm2.walk_and_cache()
    assert len(parse_calls) == 1
    assert files[0].functions[0].name == "new"


def test_deleted_file_drops_from_cache(tmp_path, store, project_id):
    p = _write(tmp_path, "a.py", "def f(): pass\n")
    _write(tmp_path, "b.py", "def g(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    rm.walk_and_cache()
    assert {r.file_path for r in store.list_repo_map_entries(project_id)} == {
        "a.py",
        "b.py",
    }

    p.unlink()
    rm.walk_and_cache()
    assert {r.file_path for r in store.list_repo_map_entries(project_id)} == {"b.py"}


def test_file_symbols_lines_count_matches_source(tmp_path, store, project_id):
    _write(tmp_path, "a.py", "x = 1\ny = 2\nz = 3\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    files = rm.walk_and_cache()
    assert files[0].lines == 3
```

- [ ] **Step 2: Run the failing tests**

```bash
pytest plugin/tests/test_repo_map_walker.py -v
```

Expected: failures with `ImportError: cannot import name 'RepoMap' from 'plugin.services.repo_map'`.

- [ ] **Step 3: Add `RepoMap` to `plugin/services/repo_map.py`**

Append to `plugin/services/repo_map.py` after the existing dataclasses + errors block. Add the new top-level imports first (at the top of the file, with the other imports):

```python
import hashlib
import json
from pathlib import Path

from plugin.services.project_store import ProjectStore
from plugin.services.repo_map_python import parse_python_file
```

Then add the constants and class:

```python
_IGNORE_DIRS = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "node_modules",
        ".git",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "target",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "htmlcov",
        ".tox",
    }
)
_IGNORE_SUFFIXES = frozenset({".pyc", ".pyo", ".so"})


def _is_ignored(rel_parts: tuple[str, ...]) -> bool:
    return any(p in _IGNORE_DIRS for p in rel_parts)


def _serialize_symbols(
    imports: list[str], classes: list[ClassSymbol], functions: list[FunctionSymbol]
) -> str:
    return json.dumps(
        {
            "imports": imports,
            "classes": [
                {"name": c.name, "bases": list(c.bases), "methods": list(c.methods)}
                for c in classes
            ],
            "functions": [{"name": f.name, "signature": f.signature} for f in functions],
        }
    )


def _deserialize_symbols(
    blob: str,
) -> tuple[list[str], list[ClassSymbol], list[FunctionSymbol]]:
    data = json.loads(blob)
    imports = list(data.get("imports", []))
    classes = [
        ClassSymbol(name=c["name"], bases=list(c["bases"]), methods=list(c["methods"]))
        for c in data.get("classes", [])
    ]
    functions = [
        FunctionSymbol(name=f["name"], signature=f["signature"])
        for f in data.get("functions", [])
    ]
    return imports, classes, functions


class RepoMap:
    """Walk a project root, populate ``repo_map_cache``, return per-file symbols."""

    def __init__(
        self, project_root: Path, store: ProjectStore, project_id: int
    ) -> None:
        self._root = project_root
        self._store = store
        self._project_id = project_id

    def walk_and_cache(self) -> list[FileSymbols]:
        if not self._root.exists() or not self._root.is_dir():
            raise ProjectRootNotAccessible(str(self._root))

        cached_by_path = {
            row.file_path: row
            for row in self._store.list_repo_map_entries(self._project_id)
        }

        results: list[FileSymbols] = []
        seen_paths: set[str] = set()

        for fs_path in self._root.rglob("*.py"):
            if not fs_path.is_file():
                continue
            rel = fs_path.relative_to(self._root)
            if _is_ignored(rel.parts):
                continue
            if rel.suffix in _IGNORE_SUFFIXES:
                continue
            rel_posix = rel.as_posix()
            seen_paths.add(rel_posix)

            content_bytes = fs_path.read_bytes()
            mtime = fs_path.stat().st_mtime
            cached = cached_by_path.get(rel_posix)
            if cached is not None and cached.mtime == mtime:
                imports, classes, functions = _deserialize_symbols(cached.symbols_json)
            else:
                sha1 = hashlib.sha1(content_bytes).hexdigest()
                if cached is not None and cached.sha1 == sha1:
                    imports, classes, functions = _deserialize_symbols(
                        cached.symbols_json
                    )
                    self._store.upsert_repo_map_entry(
                        project_id=self._project_id,
                        file_path=rel_posix,
                        mtime=mtime,
                        sha1=sha1,
                        symbols_json=cached.symbols_json,
                    )
                else:
                    imports, classes, functions = parse_python_file(content_bytes)
                    self._store.upsert_repo_map_entry(
                        project_id=self._project_id,
                        file_path=rel_posix,
                        mtime=mtime,
                        sha1=sha1,
                        symbols_json=_serialize_symbols(imports, classes, functions),
                    )

            line_count = content_bytes.count(b"\n") + (
                0 if content_bytes.endswith(b"\n") or not content_bytes else 1
            )
            results.append(
                FileSymbols(
                    path=rel_posix,
                    lines=line_count,
                    imports=imports,
                    classes=classes,
                    functions=functions,
                )
            )

        # Drop cache rows for files that disappeared.
        self._store.delete_repo_map_entries(self._project_id, seen_paths)
        return results
```

Update the `__all__` block at the bottom to include `RepoMap`:

```python
__all__ = [
    "ClassSymbol",
    "FileSymbols",
    "FunctionSymbol",
    "ProjectRootNotAccessible",
    "RenderedMap",
    "RepoMap",
    "RepoMapError",
]
```

- [ ] **Step 4: Run the walker tests**

```bash
pytest plugin/tests/test_repo_map_walker.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Run the full suite + ruff**

```bash
ruff check .
ruff format --check .
pytest
```

Expected:
- ruff: all checks passed.
- pytest: **119 passed** (110 existing + 9 new).

If ruff complains about `S324` (insecure hash) on `hashlib.sha1`, add `# noqa: S324` to that line — sha1 here is for content fingerprinting, not security.

- [ ] **Step 6: Commit**

```bash
git add plugin/services/repo_map.py plugin/tests/test_repo_map_walker.py
git commit -m "feat(plugin): add RepoMap.walk_and_cache (mtime + sha1 incremental cache)"
```

---

## Task 7: `RepoMap.render`

**Files:**
- Modify: `plugin/services/repo_map.py`
- Create: `plugin/tests/test_repo_map_render.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_repo_map_render.py`:

```python
"""Tests for RepoMap.render."""
from __future__ import annotations

from plugin.services.repo_map import (
    ClassSymbol,
    FileSymbols,
    FunctionSymbol,
    RenderedMap,
    RepoMap,
)


def _file(path: str, lines: int = 1, imports=None, classes=None, functions=None):
    return FileSymbols(
        path=path,
        lines=lines,
        imports=list(imports or []),
        classes=list(classes or []),
        functions=list(functions or []),
    )


def test_empty_file_list_returns_empty_render():
    out = RepoMap.render([], budget_tokens=1024)
    assert isinstance(out, RenderedMap)
    assert out.text == ""
    assert out.file_count == 0
    assert out.truncated_files == []
    assert out.total_bytes == 0


def test_single_file_with_no_symbols_renders_only_header():
    f = _file("a.py", lines=10)
    out = RepoMap.render([f], budget_tokens=1024)
    assert out.text == "=== a.py (10 lines)\n"
    assert out.file_count == 1
    assert out.truncated_files == []
    assert out.total_bytes == len(out.text)


def test_imports_section_rendered_when_non_empty():
    f = _file("a.py", lines=5, imports=["os", "sys", "app.models"])
    out = RepoMap.render([f], budget_tokens=1024)
    assert "imports: os, sys, app.models\n" in out.text


def test_imports_section_omitted_when_empty():
    f = _file("a.py", lines=5, imports=[])
    out = RepoMap.render([f], budget_tokens=1024)
    assert "imports:" not in out.text


def test_classes_and_functions_rendered():
    cls = ClassSymbol(
        name="Service",
        bases=["Base"],
        methods=["def __init__(self) -> None", "async def call(self) -> str"],
    )
    fn = FunctionSymbol(name="helper", signature="def helper(x: int) -> None")
    f = _file("a.py", lines=20, classes=[cls], functions=[fn])
    out = RepoMap.render([f], budget_tokens=1024)
    assert "classes:" in out.text
    assert "  class Service(Base):" in out.text
    assert "    def __init__(self) -> None" in out.text
    assert "    async def call(self) -> str" in out.text
    assert "functions:" in out.text
    assert "  def helper(x: int) -> None" in out.text


def test_class_without_bases_renders_no_parens():
    cls = ClassSymbol(name="Plain", bases=[], methods=["def m(self): ..."])
    f = _file("a.py", lines=5, classes=[cls])
    out = RepoMap.render([f], budget_tokens=1024)
    assert "  class Plain:" in out.text
    assert "Plain():" not in out.text


def test_files_sorted_alphabetically_by_path():
    files = [
        _file("z.py"),
        _file("a.py"),
        _file("m/n.py"),
    ]
    out = RepoMap.render(files, budget_tokens=1024)
    pos_a = out.text.index("=== a.py")
    pos_m = out.text.index("=== m/n.py")
    pos_z = out.text.index("=== z.py")
    assert pos_a < pos_m < pos_z


def test_truncation_when_budget_exhausted():
    # Five files; small budget — only a couple should fit.
    files = [_file(f"file_{i:02d}.py", lines=10) for i in range(5)]
    out = RepoMap.render(files, budget_tokens=8)  # ~32 chars budget
    assert out.file_count < 5
    assert len(out.truncated_files) == 5 - out.file_count
    # Truncated files are the alphabetically-later ones.
    expected_kept = [f.path for f in files[: out.file_count]]
    expected_truncated = [f.path for f in files[out.file_count :]]
    rendered_paths = [f"file_{i:02d}.py" for i in range(5) if f"file_{i:02d}.py" in out.text]
    assert rendered_paths == expected_kept
    assert sorted(out.truncated_files) == sorted(expected_truncated)


def test_total_bytes_matches_text_length():
    f = _file("a.py", lines=5, imports=["os"])
    out = RepoMap.render([f], budget_tokens=1024)
    assert out.total_bytes == len(out.text)
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
pytest plugin/tests/test_repo_map_render.py -v
```

Expected: failures with `AttributeError: type object 'RepoMap' has no attribute 'render'`.

- [ ] **Step 3: Add `render` to the `RepoMap` class in `plugin/services/repo_map.py`**

Append the static method to the `RepoMap` class (right after `walk_and_cache`):

```python
    @staticmethod
    def render(files: list[FileSymbols], budget_tokens: int = 6144) -> RenderedMap:
        """Render an Aider-style block per file until the budget is exhausted.

        Token budget is approximated as ``len(text) // 4`` (a coarse but
        well-known heuristic). Files included up to the budget appear in
        the text; the rest are listed in ``truncated_files``. Files are
        ordered alphabetically by path.
        """
        sorted_files = sorted(files, key=lambda f: f.path)
        budget_chars = budget_tokens * 4
        chunks: list[str] = []
        included_count = 0
        truncated: list[str] = []
        cursor = 0

        for fs in sorted_files:
            block = _format_file_block(fs)
            if cursor + len(block) > budget_chars and chunks:
                truncated.append(fs.path)
                continue
            chunks.append(block)
            cursor += len(block)
            included_count += 1

        # Anything we never saw because of the early break (we don't break
        # — we continue — so this is just `truncated` already populated).
        text = "".join(chunks)
        return RenderedMap(
            text=text,
            file_count=included_count,
            truncated_files=truncated,
            total_bytes=len(text),
        )
```

Then add `_format_file_block` as a module-level helper above the class:

```python
def _format_file_block(fs: FileSymbols) -> str:
    """Render one file as the Aider-style block."""
    lines = [f"=== {fs.path} ({fs.lines} lines)\n"]
    if fs.imports:
        lines.append(f"imports: {', '.join(fs.imports)}\n")
    if fs.classes:
        lines.append("classes:\n")
        for cls in fs.classes:
            base_part = f"({', '.join(cls.bases)})" if cls.bases else ""
            lines.append(f"  class {cls.name}{base_part}:\n")
            for method in cls.methods:
                lines.append(f"    {method}\n")
    if fs.functions:
        lines.append("functions:\n")
        for fn in fs.functions:
            lines.append(f"  {fn.signature}\n")
    return "".join(lines)
```

- [ ] **Step 4: Run the render tests**

```bash
pytest plugin/tests/test_repo_map_render.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Run the full suite + ruff**

```bash
ruff check .
ruff format --check .
pytest
```

Expected:
- ruff: all checks passed.
- pytest: **128 passed** (119 existing + 9 new).

- [ ] **Step 6: Commit**

```bash
git add plugin/services/repo_map.py plugin/tests/test_repo_map_render.py
git commit -m "feat(plugin): add RepoMap.render (Aider-style block formatter with budget)"
```

---

## Task 8: Add `RepoMapResponse` to `plugin/schemas.py`

**Files:**
- Modify: `plugin/schemas.py`
- Create: `plugin/tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

Create `plugin/tests/test_schemas.py`:

```python
"""Tests for plugin.schemas Pydantic models."""
from __future__ import annotations

from plugin.schemas import RepoMapResponse


def test_repo_map_response_round_trip():
    original = RepoMapResponse(
        text="=== a.py\n",
        file_count=1,
        truncated_files=["b.py"],
        total_bytes=11,
    )
    data = original.model_dump()
    restored = RepoMapResponse.model_validate(data)
    assert restored == original


def test_repo_map_response_defaults_to_empty_truncated_list():
    r = RepoMapResponse(text="", file_count=0, total_bytes=0)
    assert r.truncated_files == []


def test_repo_map_response_rejects_negative_counts():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RepoMapResponse(text="x", file_count=-1, total_bytes=1)
    with pytest.raises(ValidationError):
        RepoMapResponse(text="x", file_count=0, total_bytes=-1)
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
pytest plugin/tests/test_schemas.py -v
```

Expected: `ImportError: cannot import name 'RepoMapResponse' from 'plugin.schemas'`.

- [ ] **Step 3: Add `RepoMapResponse` to `plugin/schemas.py`**

Add after the existing `ModelsResponse`:

```python
class RepoMapResponse(BaseModel):
    text: str
    file_count: int = Field(..., ge=0)
    truncated_files: list[str] = Field(default_factory=list)
    total_bytes: int = Field(..., ge=0)
```

Update `__all__` to include it:

```python
__all__ = [
    "ModelsResponse",
    "ProjectCreate",
    "ProjectsResponse",
    "RepoMapResponse",
]
```

- [ ] **Step 4: Run the schemas tests**

```bash
pytest plugin/tests/test_schemas.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the full suite + ruff**

```bash
ruff check .
pytest
```

Expected: 131 passed (128 + 3).

- [ ] **Step 6: Commit**

```bash
git add plugin/schemas.py plugin/tests/test_schemas.py
git commit -m "feat(plugin): add RepoMapResponse schema"
```

---

## Task 9: `GET /projects/{id}/repo_map` route

**Files:**
- Modify: `plugin/routes.py`
- Create: `plugin/tests/test_routes_repo_map.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_routes_repo_map.py`:

```python
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
    for i in range(6):
        (tmp_path / f"f{i}.py").write_text(f"def f{i}():\n    pass\n")
    pid = _make_project(store, str(tmp_path))
    c = _client_for(store)
    r = c.get(f"/api/plugins/balu_code/projects/{pid}/repo_map?budget=8")
    assert r.status_code == 200
    body = r.json()
    assert body["file_count"] < 6
    assert len(body["truncated_files"]) == 6 - body["file_count"]


def test_repo_map_401_when_auth_fails(tmp_path, store):
    from fastapi import HTTPException, status as _status

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
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
pytest plugin/tests/test_routes_repo_map.py -v
```

Expected: 4 failures (404 instead of 200/422; route not defined). The 404-for-unknown-project test may pass coincidentally because the route doesn't exist at all.

- [ ] **Step 3: Add the handler to `plugin/routes.py`**

First, extend the existing project_store import block at the top to include `ProjectNotFoundError` (already imported) and the new dependencies. Add new top-level imports:

```python
from plugin.schemas import (
    ModelsResponse,
    ProjectCreate,
    ProjectsResponse,
    RepoMapResponse,
)
from plugin.services.repo_map import ProjectRootNotAccessible, RepoMap
```

Replace the existing `from plugin.schemas import ...` line and add the new `from plugin.services.repo_map import ...` line.

Inside `build_router`, before the final `return router`, append:

```python
    @router.get(
        "/projects/{project_id}/repo_map",
        response_model=RepoMapResponse,
        tags=["balu_code"],
    )
    async def repo_map_route(
        project_id: int,
        budget: int = 6144,
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
    ) -> RepoMapResponse:
        try:
            project = await asyncio.to_thread(store.get_project, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"project {project_id} not found",
            ) from exc

        repo_map = RepoMap(
            project_root=Path(project.root_path),
            store=store,
            project_id=project.id,
        )

        try:
            files = await asyncio.to_thread(repo_map.walk_and_cache)
        except ProjectRootNotAccessible as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"project root not accessible: {exc}",
            ) from exc

        rendered = RepoMap.render(files, budget_tokens=budget)
        return RepoMapResponse(
            text=rendered.text,
            file_count=rendered.file_count,
            truncated_files=list(rendered.truncated_files),
            total_bytes=rendered.total_bytes,
        )
```

- [ ] **Step 4: Run the route tests and verify they pass**

```bash
pytest plugin/tests/test_routes_repo_map.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Run the full suite + ruff**

```bash
ruff check .
ruff format --check .
pytest
```

Expected:
- ruff: all checks passed.
- pytest: **136 passed** (131 existing + 5 new).

- [ ] **Step 6: Commit**

```bash
git add plugin/routes.py plugin/tests/test_routes_repo_map.py
git commit -m "feat(plugin): add GET /projects/{id}/repo_map route (Python only)"
```

---

## Task 10: Phase 3a verification + push

**Files:**
- Create: `docs/phase-3a-verification.md`

- [ ] **Step 1: Run the full local CI equivalent**

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
- ruff: clean.
- pytest: ≥136 tests passing.
- `dist/` contains `balu_code-0.1.0.bhplugin`, `.sha256`, `balu_code_cli-0.1.0-py3-none-any.whl`.

- [ ] **Step 2: Verify the `.bhplugin` includes the Phase 3a modules**

```bash
python -c "
import zipfile
with zipfile.ZipFile('dist/balu_code-0.1.0.bhplugin') as zf:
    names = sorted(zf.namelist())
want = {
    'routes.py',
    'schemas.py',
    'services/repo_map.py',
    'services/repo_map_python.py',
}
missing = want - set(names)
assert not missing, f'missing in .bhplugin: {missing}'
print('ok', len(names), 'files')
"
```

Expected: `ok <N> files`.

- [ ] **Step 3: Create `docs/phase-3a-verification.md`**

Replace the bracketed values with your actual measurements.

```markdown
# Phase 3a verification — 2026-04-18

## Environment (local dev)

- Commit: `<git rev-parse --short HEAD>`
- Python: 3.13.5 (CI matrix covers 3.11 & 3.12)

## Automated checks

- [x] `ruff check .` — clean
- [x] `ruff format --check .` — clean
- [x] `pytest -v` — `<N>` tests passing
- [x] `python -m scripts.build_bhplugin` includes
      `routes.py`, `schemas.py`, `services/repo_map.py`,
      `services/repo_map_python.py`, plus the Phase-2 modules
- [x] `python -m scripts.build_wheel` still produces the CLI wheel
- [ ] GitHub Actions: CI green on `main` (fill in after push)

## Manual checks against dev BaluHost

- [ ] Re-sideload the new `.bhplugin` into
      `/opt/baluhost/backend/app/plugins/installed/balu_code/`
- [ ] BaluHost venv installs `tree-sitter` and `tree-sitter-python`
      (from the new `python_requirements`)
- [ ] Restart the BaluHost backend
- [ ] `GET /api/plugins/balu_code/projects/{id}/repo_map` against a
      registered Python project returns `text` + `file_count > 0`
- [ ] `?budget=512` truncates as expected

## Plan deviations

(Fill in any divergences encountered during the 10 tasks. Use
`git log --oneline a7bad2c..HEAD` to enumerate commits — anything that
isn't a `feat:` matching a task title was a follow-up.)

## Known issues carried into Phase 3b

- Repo-map only covers Python; TypeScript/Go are deferred.
- Token approximation is `len(text) // 4`; real tokenizer lands when
  the agent loop ships in Phase 4.
- Smart ranker (recently-edited / import-weight / opened-in-chat) is
  still TODO; alphabetical sort for now.
- Walks happen synchronously inside the request handler. First call on
  a large repo is slow; subsequent calls are cache-fast. Background
  job machinery comes with `POST /projects/{id}/index` in Phase 3b.
```

- [ ] **Step 4: Commit + push**

```bash
git add docs/phase-3a-verification.md
git commit -m "docs: add Phase 3a verification checklist"
git push
```

- [ ] **Step 5: Verify CI on GitHub**

```bash
sleep 40
gh run list --limit 2
```

Expected: the new push's CI run is `completed success`. If `in_progress`, poll again with `sleep 20 && gh run list --limit 2` until it completes (max 3 min total).

Once green, update the verification doc with the actual run URL and push that as a tiny follow-up commit.

---

## Phase 3a Definition of Done

- All 10 tasks committed and pushed to `main`.
- CI green on `main` (both 3.11 and 3.12 matrix jobs).
- Full suite ≥136 tests, all green locally.
- `plugin/__init__.py` is back under 100 lines; `routes.py` and `schemas.py` carry the route surface.
- `.bhplugin` archive includes `routes.py`, `schemas.py`, `services/repo_map.py`, `services/repo_map_python.py`.
- `GET /api/plugins/balu_code/projects/{id}/repo_map` works against a registered Python project (manual verification against dev BaluHost).

## What comes next (not this plan)

- **Phase 3b — RAG + indexing routes.** `services/rag_index.py` (sqlite-vec, per-project DB), embedding pipeline using `OllamaClient.embed`, `POST /projects/{id}/index` + `GET /projects/{id}/index/status`, top-K retrieval. Tree-sitter walker is reused for chunk boundaries.
- **Phase 4 — Agent loop + tools + WebSocket `/chat`.**
- **Phase 5 — CLI: `auth`, `init`, `models`, `index`, `chat` Textual TUI.**
