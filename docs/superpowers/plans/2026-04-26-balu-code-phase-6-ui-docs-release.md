# Balu Code Phase 6 — UI Bundle, Docs, Release — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the web settings panel (4-tab React bundle), user-facing docs, and an automated release pipeline for Balu Code v0.1.0.

**Architecture:** A monolithic `plugin/ui/bundle.js` follows the existing `storage_analytics` pattern — plain JS using `window.React`, dark Tailwind classes, `export default`. Three new backend endpoints (`GET/PUT /config`, `GET /logs`) support the Config and Logs tabs. Config is persisted as `plugin_config.json` in the data dir. Docs are three Markdown files. `scripts/release.py` bumps versions, commits, tags, and pushes; two new CI jobs create the GitHub Release and publish the wheel to TestPyPI.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, plain ES-module JavaScript (no build step), SQLAlchemy (for audit log query), PyYAML, `subprocess` (release script), GitHub Actions.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `plugin/services/config_store.py` | Create | load/save `BaluCodePluginConfig` as JSON in data dir |
| `plugin/deps.py` | Modify | add `_data_dir`, `get_data_dir()`, `update_plugin_config()` |
| `plugin/__init__.py` | Modify | `on_startup` loads persisted config; add `get_ui_manifest()` |
| `plugin/schemas.py` | Modify | add `ConfigUpdateRequest`, `LogEntry`, `LogsResponse` |
| `plugin/services/audit.py` | Modify | add `query_recent_tool_calls()` returning `list[dict]` |
| `plugin/routes.py` | Modify | add `GET /config`, `PUT /config`, `GET /logs` |
| `plugin/tests/fixtures/baluhost_stub/app/plugins/base.py` | Modify | add `PluginNavItem`, `PluginUIManifest` |
| `plugin/tests/test_config_store.py` | Create | tests for config persistence |
| `plugin/tests/test_routes_config_logs.py` | Create | tests for the 3 new routes |
| `plugin/ui/bundle.js` | Create | 4-tab React UI (Models / Projects / Config / Logs) |
| `docs/install.md` | Create | server-side setup guide |
| `docs/cli.md` | Create | CLI command reference |
| `docs/config.md` | Create | full configuration reference |
| `docs/CHANGELOG.md` | Create | hand-maintained release notes |
| `docs/marketplace-submission.md` | Create | manual submission guide |
| `scripts/release.py` | Create | version bump + commit + tag + push |
| `scripts/tests/test_release.py` | Create | tests for bump functions |
| `.github/workflows/ci.yml` | Modify | add `release` + `publish-cli` jobs |

---

## Task 1: Config persistence service

**Files:**
- Create: `plugin/services/config_store.py`
- Create: `plugin/tests/test_config_store.py`

- [ ] **Step 1: Write the failing test**

```python
# plugin/tests/test_config_store.py
from __future__ import annotations

import json

import pytest

from plugin.config import BaluCodePluginConfig
from plugin.services.config_store import load_plugin_config, save_plugin_config


def test_load_returns_defaults_when_file_missing(tmp_path):
    cfg = load_plugin_config(tmp_path)
    assert cfg == BaluCodePluginConfig()


def test_save_then_load_round_trips(tmp_path):
    original = BaluCodePluginConfig(chat_model="qwen2.5-coder:7b", temperature=0.5)
    save_plugin_config(original, tmp_path)
    loaded = load_plugin_config(tmp_path)
    assert loaded == original


def test_save_writes_valid_json(tmp_path):
    save_plugin_config(BaluCodePluginConfig(), tmp_path)
    data = json.loads((tmp_path / "plugin_config.json").read_text())
    assert data["chat_model"] == "qwen2.5-coder:14b-instruct-q4_K_M"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/sven/projects/plugins/Balu_Code
pytest plugin/tests/test_config_store.py -v
```

Expected: `ImportError: cannot import name 'load_plugin_config'`

- [ ] **Step 3: Create `plugin/services/config_store.py`**

```python
"""Persist and load BaluCodePluginConfig as JSON in the plugin data dir."""
from __future__ import annotations

import json
from pathlib import Path

from plugin.config import BaluCodePluginConfig

_CONFIG_FILE = "plugin_config.json"


def load_plugin_config(data_dir: Path) -> BaluCodePluginConfig:
    path = data_dir / _CONFIG_FILE
    if not path.exists():
        return BaluCodePluginConfig()
    return BaluCodePluginConfig.model_validate(json.loads(path.read_text()))


def save_plugin_config(config: BaluCodePluginConfig, data_dir: Path) -> None:
    (data_dir / _CONFIG_FILE).write_text(config.model_dump_json())


__all__ = ["load_plugin_config", "save_plugin_config"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest plugin/tests/test_config_store.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/services/config_store.py plugin/tests/test_config_store.py
git commit -m "feat(plugin): add config persistence service"
```

---

## Task 2: Wire config_store into deps + on_startup

**Files:**
- Modify: `plugin/deps.py`
- Modify: `plugin/__init__.py`

- [ ] **Step 1: Extend `plugin/deps.py`**

Add `_data_dir` singleton, `get_data_dir()`, `update_plugin_config()`, and `data_dir` parameter to `set_singletons` / `clear_singletons`.

The complete new `deps.py` (replace in full):

```python
"""Module-level singletons for the balu_code plugin."""
from __future__ import annotations

from pathlib import Path

from plugin.config import BaluCodePluginConfig
from plugin.services.audit import AuditLogger
from plugin.services.index_jobs import IndexJobTracker
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore
from plugin.services.rag_registry import RagRegistry
from plugin.services.tools import ToolRegistry

_store: ProjectStore | None = None
_ollama: OllamaClient | None = None
_rag_registry: RagRegistry | None = None
_index_job_tracker: IndexJobTracker | None = None
_tool_registry: ToolRegistry | None = None
_plugin_config: BaluCodePluginConfig | None = None
_audit_log: AuditLogger | None = None
_data_dir: Path | None = None


def set_singletons(
    store: ProjectStore,
    ollama: OllamaClient,
    rag_registry: RagRegistry,
    index_job_tracker: IndexJobTracker,
    tool_registry: ToolRegistry,
    plugin_config: BaluCodePluginConfig,
    audit_log: AuditLogger,
    data_dir: Path,
) -> None:
    global _store, _ollama, _rag_registry, _index_job_tracker, _tool_registry
    global _plugin_config, _audit_log, _data_dir
    _store = store
    _ollama = ollama
    _rag_registry = rag_registry
    _index_job_tracker = index_job_tracker
    _tool_registry = tool_registry
    _plugin_config = plugin_config
    _audit_log = audit_log
    _data_dir = data_dir


def clear_singletons() -> None:
    global _store, _ollama, _rag_registry, _index_job_tracker, _tool_registry
    global _plugin_config, _audit_log, _data_dir
    _store = None
    _ollama = None
    _rag_registry = None
    _index_job_tracker = None
    _tool_registry = None
    _plugin_config = None
    _audit_log = None
    _data_dir = None


def update_plugin_config(config: BaluCodePluginConfig) -> None:
    global _plugin_config
    _plugin_config = config


def get_project_store() -> ProjectStore:
    if _store is None:
        raise RuntimeError("balu_code plugin not initialized (ProjectStore missing)")
    return _store


def get_ollama_client() -> OllamaClient:
    if _ollama is None:
        raise RuntimeError("balu_code plugin not initialized (OllamaClient missing)")
    return _ollama


def get_rag_registry() -> RagRegistry:
    if _rag_registry is None:
        raise RuntimeError("balu_code plugin not initialized (RagRegistry missing)")
    return _rag_registry


def get_index_job_tracker() -> IndexJobTracker:
    if _index_job_tracker is None:
        raise RuntimeError("balu_code plugin not initialized (IndexJobTracker missing)")
    return _index_job_tracker


def get_tool_registry() -> ToolRegistry:
    if _tool_registry is None:
        raise RuntimeError("balu_code plugin not initialized (ToolRegistry missing)")
    return _tool_registry


def get_plugin_config() -> BaluCodePluginConfig:
    if _plugin_config is None:
        raise RuntimeError("balu_code plugin not initialized (BaluCodePluginConfig missing)")
    return _plugin_config


def get_audit_log() -> AuditLogger:
    if _audit_log is None:
        raise RuntimeError("balu_code plugin not initialized (AuditLogger missing)")
    return _audit_log


def get_data_dir() -> Path:
    if _data_dir is None:
        raise RuntimeError("balu_code plugin not initialized (data_dir missing)")
    return _data_dir


__all__ = [
    "clear_singletons",
    "get_audit_log",
    "get_data_dir",
    "get_index_job_tracker",
    "get_ollama_client",
    "get_plugin_config",
    "get_project_store",
    "get_rag_registry",
    "get_tool_registry",
    "set_singletons",
    "update_plugin_config",
]
```

- [ ] **Step 2: Update `on_startup` in `plugin/__init__.py`**

Replace the `set_singletons(...)` call and add `load_plugin_config`. Change:

```python
    async def on_startup(self) -> None:
        data_dir = resolve_data_dir()
        store = ProjectStore(data_dir / "store.db")
        try:
            ollama = OllamaClient(base_url=self._config.ollama_base_url)
        except BaseException:
            store.close()
            raise
        rag_registry = RagRegistry(
            data_dir=data_dir,
            embed_model=self._config.embed_model,
            ollama=ollama,
        )
        index_job_tracker = IndexJobTracker()
        tool_registry = default_registry()
        audit_log = AuditLogger(get_audit_logger_db())
        self._store = store
        self._ollama = ollama
        self._rag_registry = rag_registry
        self._index_job_tracker = index_job_tracker
        self._tool_registry = tool_registry
        set_singletons(
            store,
            ollama,
            rag_registry,
            index_job_tracker,
            tool_registry,
            self._config,
            audit_log,
        )
```

To:

```python
    async def on_startup(self) -> None:
        from plugin.services.config_store import load_plugin_config
        data_dir = resolve_data_dir()
        self._config = load_plugin_config(data_dir)
        store = ProjectStore(data_dir / "store.db")
        try:
            ollama = OllamaClient(base_url=self._config.ollama_base_url)
        except BaseException:
            store.close()
            raise
        rag_registry = RagRegistry(
            data_dir=data_dir,
            embed_model=self._config.embed_model,
            ollama=ollama,
        )
        index_job_tracker = IndexJobTracker()
        tool_registry = default_registry()
        audit_log = AuditLogger(get_audit_logger_db())
        self._store = store
        self._ollama = ollama
        self._rag_registry = rag_registry
        self._index_job_tracker = index_job_tracker
        self._tool_registry = tool_registry
        set_singletons(
            store,
            ollama,
            rag_registry,
            index_job_tracker,
            tool_registry,
            self._config,
            audit_log,
            data_dir,
        )
```

- [ ] **Step 3: Run full plugin test suite**

```bash
pytest plugin/tests/ -v
```

Expected: all existing tests PASS (no regressions — `clear_singletons` signature unchanged, lifecycle tests pass `data_dir` via `on_startup`).

- [ ] **Step 4: Commit**

```bash
git add plugin/deps.py plugin/__init__.py
git commit -m "feat(plugin): wire config_store + data_dir singleton into deps"
```

---

## Task 3: GET /config and PUT /config routes

**Files:**
- Modify: `plugin/schemas.py`
- Modify: `plugin/routes.py`
- Create: `plugin/tests/test_routes_config_logs.py` (partial — config tests only)

- [ ] **Step 1: Add schemas to `plugin/schemas.py`**

Add after the `IndexStatusResponse` class:

```python
from pydantic import ConfigDict


class ConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ollama_base_url: str | None = None
    chat_model: str | None = None
    embed_model: str | None = None
    context_window: int | None = None
    repo_map_budget: int | None = None
    rag_budget: int | None = None
    rag_top_k: int | None = None
    max_iterations: int | None = None
    max_total_tokens_per_turn: int | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
```

Also update `__all__` to include `"ConfigUpdateRequest"`.

- [ ] **Step 2: Write the failing tests**

```python
# plugin/tests/test_routes_config_logs.py
from __future__ import annotations

import pytest
from app.api.deps import get_current_user
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin import BaluCodePlugin
from plugin.config import BaluCodePluginConfig
from plugin.deps import get_audit_log, get_data_dir, get_plugin_config


def _make_app(tmp_path, config=None):
    cfg = config or BaluCodePluginConfig()
    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_plugin_config] = lambda: cfg
    app.dependency_overrides[get_data_dir] = lambda: tmp_path
    app.dependency_overrides[get_audit_log] = lambda: _FakeAuditLog()
    return app


class _FakeAuditLog:
    async def record_tool_call(self, **kwargs) -> None:
        pass

    async def query_recent_tool_calls(self, limit: int = 100) -> list[dict]:
        return [
            {
                "id": 1,
                "timestamp": "2026-04-26T10:00:00",
                "user": "admin",
                "action": "tool:read_file",
                "resource": "/home/user/foo.py",
                "success": True,
                "error_message": None,
                "turn_id": "t1",
                "tool_call_id": "tc1",
            }
        ]


def test_get_config_returns_current_config(tmp_path):
    cfg = BaluCodePluginConfig(chat_model="qwen2.5-coder:7b")
    client = TestClient(_make_app(tmp_path, cfg))
    r = client.get("/api/plugins/balu_code/config")
    assert r.status_code == 200
    assert r.json()["chat_model"] == "qwen2.5-coder:7b"


def test_put_config_updates_and_persists(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.put(
        "/api/plugins/balu_code/config",
        json={"chat_model": "qwen2.5-coder:7b", "temperature": 0.8},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["chat_model"] == "qwen2.5-coder:7b"
    assert body["temperature"] == 0.8
    # persisted to disk
    from plugin.services.config_store import load_plugin_config
    saved = load_plugin_config(tmp_path)
    assert saved.chat_model == "qwen2.5-coder:7b"


def test_put_config_rejects_unknown_field(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.put("/api/plugins/balu_code/config", json={"unknown_field": "x"})
    assert r.status_code == 422


def test_put_config_rejects_invalid_temperature(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.put("/api/plugins/balu_code/config", json={"temperature": 5.0})
    assert r.status_code == 422
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest plugin/tests/test_routes_config_logs.py::test_get_config_returns_current_config -v
```

Expected: FAIL — route not defined yet.

- [ ] **Step 4: Add `GET /config` and `PUT /config` to `plugin/routes.py`**

Add these two imports at the top of `build_router` (alongside existing imports):

```python
from pathlib import Path

from plugin.deps import get_data_dir, update_plugin_config
from plugin.schemas import ConfigUpdateRequest
from plugin.services.config_store import save_plugin_config
```

Add these two routes inside `build_router()`, after the `health` route:

```python
    @router.get("/config", response_model=BaluCodePluginConfig, tags=["balu_code"])
    async def get_config_route(
        _user: UserPublic = Depends(get_current_user),
        config: BaluCodePluginConfig = Depends(get_plugin_config),
    ) -> BaluCodePluginConfig:
        return config

    @router.put("/config", response_model=BaluCodePluginConfig, tags=["balu_code"])
    async def put_config_route(
        body: ConfigUpdateRequest,
        _user: UserPublic = Depends(get_current_user),
        config: BaluCodePluginConfig = Depends(get_plugin_config),
        data_dir: Path = Depends(get_data_dir),
    ) -> BaluCodePluginConfig:
        merged = config.model_dump()
        merged.update(body.model_dump(exclude_none=True))
        new_config = BaluCodePluginConfig.model_validate(merged)
        await asyncio.to_thread(save_plugin_config, new_config, data_dir)
        update_plugin_config(new_config)
        return new_config
```

Note: `BaluCodePluginConfig` and `asyncio` are already imported in `routes.py`. Add `from plugin.deps import get_data_dir, update_plugin_config` and `from plugin.schemas import ConfigUpdateRequest` and `from plugin.services.config_store import save_plugin_config` to the top-level imports block.

- [ ] **Step 5: Run config tests**

```bash
pytest plugin/tests/test_routes_config_logs.py -k "config" -v
```

Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/schemas.py plugin/routes.py plugin/tests/test_routes_config_logs.py
git commit -m "feat(plugin): add GET/PUT /config endpoints"
```

---

## Task 4: GET /logs route

**Files:**
- Modify: `plugin/services/audit.py`
- Modify: `plugin/schemas.py`
- Modify: `plugin/routes.py`
- Modify: `plugin/tests/test_routes_config_logs.py` (add logs tests)

- [ ] **Step 1: Add `LogEntry` schema to `plugin/schemas.py`**

Add after `ConfigUpdateRequest`:

```python
class LogEntry(BaseModel):
    id: int
    timestamp: str
    user: str | None
    action: str
    resource: str | None
    success: bool
    error_message: str | None = None
    turn_id: str | None = None
    tool_call_id: str | None = None


class LogsResponse(BaseModel):
    entries: list[LogEntry]
```

Add `"LogEntry"` and `"LogsResponse"` to `__all__`.

- [ ] **Step 2: Add `query_recent_tool_calls` to `AuditLogger` in `plugin/services/audit.py`**

Add this method to the `AuditLogger` class (after `record_tool_call`):

```python
    async def query_recent_tool_calls(self, limit: int = 100) -> list[dict]:
        return await asyncio.to_thread(self._query_sync, limit)

    def _query_sync(self, limit: int) -> list[dict]:
        import json as _json

        from app.core.database import SessionLocal
        from app.models.audit_log import AuditLog as DBLog

        with SessionLocal() as db:
            if db is None:
                return []
            rows = (
                db.query(DBLog)
                .filter(DBLog.event_type == "BALU_CODE")
                .order_by(DBLog.timestamp.desc())
                .limit(limit)
                .all()
            )
            result = []
            for r in rows:
                details = _json.loads(r.details) if r.details else {}
                result.append(
                    {
                        "id": r.id,
                        "timestamp": r.timestamp.isoformat(),
                        "user": r.user,
                        "action": r.action,
                        "resource": r.resource,
                        "success": r.success,
                        "error_message": r.error_message,
                        "turn_id": details.get("turn_id"),
                        "tool_call_id": details.get("tool_call_id"),
                    }
                )
            return result
```

Note: `app.core.database` and `app.models.audit_log` are lazy imports inside `_query_sync`. In tests the `get_audit_log` dep is overridden, so `_query_sync` is never called and the lazy imports are never evaluated — no stub needed.

- [ ] **Step 3: Write failing logs test** (add to `test_routes_config_logs.py`)

```python
def test_get_logs_returns_entries(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/logs")
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body
    assert len(body["entries"]) == 1
    assert body["entries"][0]["action"] == "tool:read_file"


def test_get_logs_respects_limit(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/logs?limit=50")
    assert r.status_code == 200


def test_get_logs_rejects_excessive_limit(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/logs?limit=501")
    assert r.status_code == 422
```

- [ ] **Step 4: Run to verify failure**

```bash
pytest plugin/tests/test_routes_config_logs.py::test_get_logs_returns_entries -v
```

Expected: FAIL — route not defined yet.

- [ ] **Step 5: Add `GET /logs` to `plugin/routes.py`**

Add `LogsResponse`, `LogEntry` to the imports from `plugin.schemas`. Add after the config routes:

```python
    @router.get("/logs", response_model=LogsResponse, tags=["balu_code"])
    async def get_logs_route(
        limit: int = Query(default=100, ge=1, le=500),
        _user: UserPublic = Depends(get_current_user),
        audit_log: AuditLogger = Depends(get_audit_log),
    ) -> LogsResponse:
        raw = await audit_log.query_recent_tool_calls(limit)
        return LogsResponse(entries=[LogEntry.model_validate(d) for d in raw])
```

Add `LogEntry, LogsResponse` to the import from `plugin.schemas`. Add `AuditLogger` import from `plugin.services.audit` if not already present (it is already imported indirectly via `get_audit_log` — check existing imports and add if needed).

- [ ] **Step 6: Run all config + logs tests**

```bash
pytest plugin/tests/test_routes_config_logs.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 7: Run full suite to check no regressions**

```bash
pytest plugin/tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add plugin/services/audit.py plugin/schemas.py plugin/routes.py plugin/tests/test_routes_config_logs.py
git commit -m "feat(plugin): add GET /logs endpoint + query_recent_tool_calls"
```

---

## Task 5: Plugin UI manifest

**Files:**
- Modify: `plugin/tests/fixtures/baluhost_stub/app/plugins/base.py`
- Modify: `plugin/__init__.py`

- [ ] **Step 1: Add `PluginNavItem` and `PluginUIManifest` to the stub**

Add to `plugin/tests/fixtures/baluhost_stub/app/plugins/base.py` after `PluginMetadata`:

```python
class PluginNavItem(BaseModel):
    path: str
    label: str
    icon: str = "plug"
    admin_only: bool = False
    order: int = 100


class PluginUIManifest(BaseModel):
    enabled: bool = True
    nav_items: list[PluginNavItem] = Field(default_factory=list)
    bundle_path: str = "ui/bundle.js"
    styles_path: str | None = None
    dashboard_widgets: list[str] = Field(default_factory=list)
```

Also add `Optional` to the typing imports if not present.

- [ ] **Step 2: Write failing test for `get_ui_manifest`**

Add to `plugin/tests/test_metadata.py` (or create it if it only tests other things — check file exists first):

```python
def test_get_ui_manifest_returns_manifest_with_nav_item():
    from app.plugins.base import PluginUIManifest
    p = BaluCodePlugin()
    manifest = p.get_ui_manifest()
    assert isinstance(manifest, PluginUIManifest)
    assert manifest.bundle_path == "ui/bundle.js"
    assert len(manifest.nav_items) >= 1
    assert manifest.nav_items[0].label == "Balu Code"
```

Run:

```bash
pytest plugin/tests/test_metadata.py -v -k "ui_manifest"
```

Expected: FAIL — method returns `None`.

- [ ] **Step 3: Add `get_ui_manifest` to `plugin/__init__.py`**

Add this method to `BaluCodePlugin`:

```python
    def get_ui_manifest(self):
        from app.plugins.base import PluginNavItem, PluginUIManifest

        return PluginUIManifest(
            enabled=True,
            bundle_path="ui/bundle.js",
            nav_items=[
                PluginNavItem(path="/", label="Balu Code", icon="code-2", order=10),
            ],
        )
```

- [ ] **Step 4: Run test**

```bash
pytest plugin/tests/test_metadata.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/__init__.py plugin/tests/fixtures/baluhost_stub/app/plugins/base.py plugin/tests/test_metadata.py
git commit -m "feat(plugin): add get_ui_manifest with Balu Code nav item"
```

---

## Task 6: UI bundle — scaffold + Models tab

**Files:**
- Create: `plugin/ui/bundle.js`

No automated tests for the JS bundle. Verify visually after sideloading.

- [ ] **Step 1: Create `plugin/ui/bundle.js` with scaffold + Models tab**

```javascript
/**
 * Balu Code Plugin UI — single-file React bundle.
 * Uses window.React from the BaluHost host app. No build step.
 */

const React = window.React;
const { useState, useEffect, useCallback } = React;
const ce = React.createElement;

const API = '/api/plugins/balu_code';

async function api(path, opts = {}) {
  const token = localStorage.getItem('token');
  const res = await fetch(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

// ── Shared UI atoms ──────────────────────────────────────────────────────────

function Card({ children, className = '' }) {
  return ce('div', { className: `rounded-xl border border-slate-800 bg-slate-900/50 p-6 ${className}` }, children);
}

function Btn({ children, onClick, disabled, variant = 'primary' }) {
  const base = 'px-4 py-2 text-sm font-medium rounded-lg disabled:opacity-50 transition-colors';
  const styles = {
    primary: 'bg-sky-500/20 text-sky-400 hover:bg-sky-500/30',
    danger:  'bg-red-500/20 text-red-400 hover:bg-red-500/30',
    ghost:   'text-slate-400 hover:text-slate-200 hover:bg-slate-800',
  };
  return ce('button', { onClick, disabled, className: `${base} ${styles[variant]}` }, children);
}

function Badge({ text, ok }) {
  const cls = ok
    ? 'text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400'
    : 'text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400';
  return ce('span', { className: cls }, text);
}

function ErrorBox({ msg }) {
  if (!msg) return null;
  return ce('div', { className: 'p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm' }, msg);
}

function Spinner() {
  return ce('div', { className: 'flex items-center justify-center h-32' },
    ce('div', { className: 'animate-spin rounded-full h-8 w-8 border-b-2 border-sky-500' })
  );
}

// ── Models tab ───────────────────────────────────────────────────────────────

function ModelsTab() {
  const [models, setModels] = useState(null);
  const [config, setConfig] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api('/models'), api('/config')])
      .then(([m, c]) => { setModels(m.models); setConfig(c); })
      .catch(e => setError(e.message));
  }, []);

  if (error) return ce(ErrorBox, { msg: error });
  if (!models) return ce(Spinner);

  return ce('div', { className: 'space-y-4' },
    ce('h2', { className: 'text-lg font-semibold text-white' }, 'Available Models'),
    ce('p', { className: 'text-sm text-slate-400' }, 'Models available on the Ollama server. Chat and embed models are set in Config.'),
    ce('div', { className: 'space-y-2' },
      models.length === 0
        ? ce('p', { className: 'text-slate-500 text-sm' }, 'No models found — is Ollama running?')
        : models.map(m =>
            ce(Card, { key: m.name, className: 'flex items-center justify-between py-3' },
              ce('div', null,
                ce('div', { className: 'text-white font-medium' }, m.name),
                m.size ? ce('div', { className: 'text-xs text-slate-500 mt-0.5' }, `${(m.size / 1e9).toFixed(1)} GB`) : null
              ),
              ce('div', { className: 'flex gap-2' },
                config?.chat_model === m.name  ? ce(Badge, { text: 'chat',  ok: true }) : null,
                config?.embed_model === m.name ? ce(Badge, { text: 'embed', ok: true }) : null,
              )
            )
          )
    )
  );
}

// ── (remaining tabs follow in Task 7–9) ──────────────────────────────────────

// ── Main shell ───────────────────────────────────────────────────────────────

const TABS = [
  { id: 'models',   label: 'Models' },
  { id: 'projects', label: 'Projects' },
  { id: 'config',   label: 'Config' },
  { id: 'logs',     label: 'Logs' },
];

function BaluCode({ user }) {
  const [tab, setTab] = useState('models');

  const content = {
    models:   ce(ModelsTab),
    projects: ce('div', { className: 'text-slate-400 text-sm' }, 'Projects tab — coming soon'),
    config:   ce('div', { className: 'text-slate-400 text-sm' }, 'Config tab — coming soon'),
    logs:     ce('div', { className: 'text-slate-400 text-sm' }, 'Logs tab — coming soon'),
  };

  return ce('div', { className: 'space-y-6' },
    ce('div', { className: 'flex gap-1 border-b border-slate-800 pb-0' },
      TABS.map(t =>
        ce('button', {
          key: t.id,
          onClick: () => setTab(t.id),
          className: `px-4 py-2 text-sm font-medium transition-colors ${
            tab === t.id
              ? 'text-sky-400 border-b-2 border-sky-400 -mb-px'
              : 'text-slate-400 hover:text-slate-200'
          }`,
        }, t.label)
      )
    ),
    ce('div', null, content[tab])
  );
}

export default BaluCode;
```

- [ ] **Step 2: Verify `bundle.js` is included in the `.bhplugin` build**

```bash
python -m scripts.build_bhplugin --repo-root . --dist dist/
python -c "
import zipfile
with zipfile.ZipFile('dist/balu_code-0.1.0.bhplugin') as zf:
    print([n for n in zf.namelist() if 'ui/' in n])
"
```

Expected: `['ui/bundle.js']` printed.

- [ ] **Step 3: Commit**

```bash
git add plugin/ui/bundle.js
git commit -m "feat(ui): scaffold bundle + Models tab"
```

---

## Task 7: UI bundle — Projects tab

**Files:**
- Modify: `plugin/ui/bundle.js`

- [ ] **Step 1: Replace the Projects placeholder with the full `ProjectsTab` component**

Add the following function before `const TABS = [...]` in `bundle.js`, replacing nothing (insert as new function):

```javascript
function ProjectsTab() {
  const [projects, setProjects] = useState(null);
  const [error, setError] = useState(null);
  const [name, setName] = useState('');
  const [rootPath, setRootPath] = useState('');
  const [creating, setCreating] = useState(false);
  const [indexing, setIndexing] = useState({});   // { [id]: 'running' | 'done' | 'error' }

  const load = useCallback(() => {
    api('/projects')
      .then(r => setProjects(r.projects))
      .catch(e => setError(e.message));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function create() {
    if (!name.trim() || !rootPath.trim()) return;
    setCreating(true);
    try {
      await api('/projects', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), root_path: rootPath.trim(), config_yaml: null }),
      });
      setName(''); setRootPath('');
      load();
    } catch (e) { setError(e.message); }
    finally { setCreating(false); }
  }

  async function del(id) {
    try { await api(`/projects/${id}`, { method: 'DELETE' }); load(); }
    catch (e) { setError(e.message); }
  }

  async function startIndex(id) {
    setIndexing(prev => ({ ...prev, [id]: 'running' }));
    setError(null);
    try {
      const { job_id } = await api(`/index/${id}`, { method: 'POST' });
      const poll = setInterval(async () => {
        const s = await api(`/index/${id}/status`).catch(() => null);
        if (!s) return;
        if (s.status === 'done') {
          setIndexing(prev => ({ ...prev, [id]: 'done' }));
          clearInterval(poll);
        } else if (s.status === 'error') {
          setError(s.error || 'Index failed');
          setIndexing(prev => ({ ...prev, [id]: 'error' }));
          clearInterval(poll);
        }
      }, 1500);
    } catch (e) { setError(e.message); setIndexing(prev => ({ ...prev, [id]: 'error' })); }
  }

  if (!projects) return ce(Spinner);

  const inputCls = 'bg-slate-800 border border-slate-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-sky-500 w-full';

  return ce('div', { className: 'space-y-6' },
    ce(ErrorBox, { msg: error }),

    // Create form
    ce(Card, null,
      ce('h3', { className: 'text-white font-medium mb-4' }, 'Add Project'),
      ce('div', { className: 'grid grid-cols-1 md:grid-cols-2 gap-3 mb-3' },
        ce('input', { placeholder: 'Name', value: name, onChange: e => setName(e.target.value), className: inputCls }),
        ce('input', { placeholder: '/absolute/path/to/project', value: rootPath, onChange: e => setRootPath(e.target.value), className: inputCls })
      ),
      ce(Btn, { onClick: create, disabled: creating || !name.trim() || !rootPath.trim() },
        creating ? 'Creating…' : 'Create Project'
      )
    ),

    // Project list
    projects.length === 0
      ? ce('p', { className: 'text-slate-500 text-sm' }, 'No projects yet.')
      : ce('div', { className: 'space-y-3' },
          projects.map(p =>
            ce(Card, { key: p.id, className: 'flex items-center justify-between gap-4 py-4' },
              ce('div', { className: 'min-w-0' },
                ce('div', { className: 'text-white font-medium truncate' }, p.name),
                ce('div', { className: 'text-xs text-slate-500 truncate' }, p.root_path)
              ),
              ce('div', { className: 'flex gap-2 shrink-0' },
                ce(Btn, {
                  onClick: () => startIndex(p.id),
                  disabled: indexing[p.id] === 'running',
                  variant: 'ghost',
                },
                  indexing[p.id] === 'running' ? 'Indexing…'
                  : indexing[p.id] === 'done'  ? 'Re-index'
                  : 'Index'
                ),
                ce(Btn, { onClick: () => del(p.id), variant: 'danger' }, 'Delete')
              )
            )
          )
        )
  );
}
```

Then replace the Projects placeholder in `content`:

```javascript
    projects: ce(ProjectsTab),
```

- [ ] **Step 2: Run the build check**

```bash
python -m scripts.build_bhplugin --repo-root . --dist dist/
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add plugin/ui/bundle.js
git commit -m "feat(ui): add Projects tab"
```

---

## Task 8: UI bundle — Config tab

**Files:**
- Modify: `plugin/ui/bundle.js`

- [ ] **Step 1: Add `ConfigTab` component before `const TABS`**

```javascript
const CONFIG_FIELDS = [
  { key: 'ollama_base_url',            label: 'Ollama Base URL',              type: 'text' },
  { key: 'chat_model',                 label: 'Chat Model',                   type: 'text' },
  { key: 'embed_model',                label: 'Embed Model',                  type: 'text' },
  { key: 'context_window',             label: 'Context Window (tokens)',       type: 'number' },
  { key: 'repo_map_budget',            label: 'Repo Map Budget (tokens)',      type: 'number' },
  { key: 'rag_budget',                 label: 'RAG Budget (tokens)',           type: 'number' },
  { key: 'rag_top_k',                  label: 'RAG Top K',                    type: 'number' },
  { key: 'max_iterations',             label: 'Max Iterations',               type: 'number' },
  { key: 'max_total_tokens_per_turn',  label: 'Max Total Tokens / Turn',      type: 'number' },
  { key: 'temperature',                label: 'Temperature (0–2)',             type: 'number', step: 0.1 },
];

function ConfigTab() {
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api('/config').then(setForm).catch(e => setError(e.message));
  }, []);

  function set(key, value) {
    setForm(prev => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  async function save() {
    setSaving(true); setError(null);
    try {
      const updated = await api('/config', { method: 'PUT', body: JSON.stringify(form) });
      setForm(updated);
      setSaved(true);
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  }

  if (!form) return ce(Spinner);

  const inputCls = 'bg-slate-800 border border-slate-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-sky-500 w-full';

  return ce('div', { className: 'space-y-6' },
    ce(ErrorBox, { msg: error }),
    ce(Card, null,
      ce('h3', { className: 'text-white font-medium mb-4' }, 'Plugin Configuration'),
      ce('div', { className: 'space-y-4' },
        CONFIG_FIELDS.map(f =>
          ce('div', { key: f.key },
            ce('label', { className: 'block text-sm text-slate-400 mb-1' }, f.label),
            ce('input', {
              type: f.type,
              step: f.step,
              value: form[f.key] ?? '',
              onChange: e => set(f.key, f.type === 'number' ? Number(e.target.value) : e.target.value),
              className: inputCls,
            })
          )
        )
      ),
      ce('div', { className: 'flex items-center gap-3 mt-6' },
        ce(Btn, { onClick: save, disabled: saving }, saving ? 'Saving…' : 'Save'),
        saved ? ce('span', { className: 'text-sm text-emerald-400' }, 'Saved!') : null
      )
    )
  );
}
```

Replace the Config placeholder:

```javascript
    config:   ce(ConfigTab),
```

- [ ] **Step 2: Commit**

```bash
git add plugin/ui/bundle.js
git commit -m "feat(ui): add Config tab"
```

---

## Task 9: UI bundle — Logs tab

**Files:**
- Modify: `plugin/ui/bundle.js`

- [ ] **Step 1: Add `LogsTab` component before `const TABS`**

```javascript
function LogsTab() {
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState(null);
  const [limit, setLimit] = useState(100);

  const load = useCallback(() => {
    api(`/logs?limit=${limit}`)
      .then(r => setEntries(r.entries))
      .catch(e => setError(e.message));
  }, [limit]);

  useEffect(() => { load(); }, [load]);

  if (error) return ce(ErrorBox, { msg: error });
  if (!entries) return ce(Spinner);

  function fmt(ts) {
    try { return new Date(ts).toLocaleString(); } catch { return ts; }
  }

  return ce('div', { className: 'space-y-4' },
    ce('div', { className: 'flex items-center justify-between' },
      ce('h2', { className: 'text-lg font-semibold text-white' }, 'Audit Log'),
      ce('div', { className: 'flex items-center gap-2' },
        ce('label', { className: 'text-sm text-slate-400' }, 'Limit'),
        ce('select', {
          value: limit,
          onChange: e => setLimit(Number(e.target.value)),
          className: 'bg-slate-800 border border-slate-700 text-white text-sm rounded-lg px-2 py-1',
        },
          [25, 50, 100, 200, 500].map(n => ce('option', { key: n, value: n }, n))
        ),
        ce(Btn, { onClick: load, variant: 'ghost' }, 'Refresh')
      )
    ),

    entries.length === 0
      ? ce('p', { className: 'text-slate-500 text-sm' }, 'No tool calls recorded yet.')
      : ce('div', { className: 'overflow-x-auto' },
          ce('table', { className: 'w-full text-sm' },
            ce('thead', null,
              ce('tr', { className: 'text-left text-slate-500 border-b border-slate-800' },
                ['Time', 'User', 'Action', 'Resource', 'Status'].map(h =>
                  ce('th', { key: h, className: 'py-2 pr-4 font-medium' }, h)
                )
              )
            ),
            ce('tbody', null,
              entries.map(e =>
                ce('tr', { key: e.id, className: 'border-b border-slate-800/50 hover:bg-slate-800/30' },
                  ce('td', { className: 'py-2 pr-4 text-slate-400 whitespace-nowrap' }, fmt(e.timestamp)),
                  ce('td', { className: 'py-2 pr-4 text-slate-300' }, e.user ?? '—'),
                  ce('td', { className: 'py-2 pr-4 text-white font-mono text-xs' }, e.action),
                  ce('td', { className: 'py-2 pr-4 text-slate-400 max-w-xs truncate' }, e.resource ?? '—'),
                  ce('td', { className: 'py-2' },
                    ce('span', {
                      className: e.success
                        ? 'text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400'
                        : 'text-xs px-2 py-0.5 rounded-full bg-red-500/20 text-red-400',
                    }, e.success ? 'ok' : 'error')
                  )
                )
              )
            )
          )
        )
  );
}
```

Replace the Logs placeholder:

```javascript
    logs:     ce(LogsTab),
```

- [ ] **Step 2: Build check**

```bash
python -m scripts.build_bhplugin --repo-root . --dist dist/
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add plugin/ui/bundle.js
git commit -m "feat(ui): add Logs tab"
```

---

## Task 10: User-facing docs

**Files:**
- Create: `docs/install.md`
- Create: `docs/cli.md`
- Create: `docs/config.md`
- Create: `docs/CHANGELOG.md`
- Create: `docs/marketplace-submission.md`

- [ ] **Step 1: Create `docs/install.md`**

```markdown
# Installing Balu Code

## Requirements

| Component | Minimum | Notes |
|-----------|---------|-------|
| BaluHost | 1.30.0 | plugin manifest version 1 |
| Python | 3.11 | server-side only |
| Ollama | 0.3.x | must be on `127.0.0.1:11434` on the BaluHost server |
| GPU VRAM | 16 GB | for `qwen2.5-coder:14b-instruct-q4_K_M` at q4 |
| GPU driver | ROCm ≥ 6.1 or CUDA ≥ 12.1 | |

**Reference hardware:** AMD RX 7900 XT (20 GB GDDR6, ROCm 6.2). Both default models run comfortably with headroom for the OS.

## 1. Set up Ollama

Install Ollama following the [official guide](https://ollama.com/download), then pull the two models Balu Code uses by default:

```bash
ollama pull qwen2.5-coder:14b-instruct-q4_K_M
ollama pull nomic-embed-text
```

Verify Ollama is accessible from the BaluHost server:

```bash
curl http://127.0.0.1:11434/api/tags
```

**ROCm note (RX 7900 XT):** Set `HSA_OVERRIDE_GFX_VERSION=11.0.0` in your Ollama systemd unit if the card is not auto-detected.

## 2. Install the plugin

1. Download `balu_code-0.1.0.bhplugin` from the [GitHub Releases page](https://github.com/Xveyn/Balu_Code/releases).
2. In the BaluHost web UI, go to **Plugins → Install plugin** and upload the `.bhplugin` file.
3. BaluHost installs and activates the plugin automatically. The sidebar shows a **Balu Code** entry.

## 3. Smoke test

Replace `<host>` and `<key>` with your BaluHost hostname and an API key:

```bash
curl -s -H "Authorization: Bearer <key>" https://<host>/api/plugins/balu_code/health
```

Expected response:

```json
{"status": "ok", "plugin": "balu_code", "version": "0.1.0"}
```

## 4. Install the CLI

On any machine that can reach the BaluHost server:

```bash
pip install balu-code-cli
balu-code auth login --server https://<host> --key <key>
```

See [cli.md](cli.md) for the full CLI reference.
```

- [ ] **Step 2: Create `docs/cli.md`**

```markdown
# Balu Code CLI Reference

Install: `pip install balu-code-cli`

## Global options

| Flag | Description |
|------|-------------|
| `--server URL` | Override the server URL from config |
| `--key KEY` | Override the API key from credentials store |

---

## auth

### `balu-code auth login`

Authenticate against a BaluHost server and store the API key.

```bash
balu-code auth login --server https://mynas.local --key balu_xxxxxxxxxxxx
```

### `balu-code auth status`

Show the currently configured server and whether the key is valid.

```bash
balu-code auth status
```

---

## init

Initialise the current directory as a Balu Code project and register it on the server.

```bash
balu-code init [--name NAME] [--path PATH]
```

If `--path` is omitted, the current working directory is used. Creates `.balucode.yaml` if absent.

---

## models

List all Ollama models available on the server.

```bash
balu-code models
```

---

## index

Start a background index job for a project.

```bash
balu-code index [PROJECT_ID]
```

If `PROJECT_ID` is omitted, uses the default project from config. Streams progress until done.

---

## chat

Open an interactive chat REPL with the coding agent.

```bash
balu-code chat [PROJECT_ID] [--yolo] [--model MODEL]
```

| Option | Description |
|--------|-------------|
| `--yolo` | Auto-approve all tool calls without prompting |
| `--model` | Override the chat model for this session |

### Approval flow

When the agent requests a tool call with `risk != "read"`, the CLI pauses and prompts:

```
[APPROVAL] write_file /home/user/src/foo.py
Allow? [y]es / [n]o / [Y]es-all / [N]o-all:
```

Priority order (first match wins):

1. `--yolo` flag → always approve
2. `.balucode.yaml` `auto_approve` list → approve if tool is listed
3. Stored permissions (`balu-code config set`) → approve or deny
4. Interactive prompt → `y`/`n` for once, `Y`/`N` for all of session

---

## session

Manage saved chat sessions. Sessions are stored as JSONL in `~/.local/share/balu-code/sessions/`.

### `balu-code session list`

```bash
balu-code session list
```

### `balu-code session resume SESSION_ID`

Replay a previous session in the terminal (server starts fresh — replay is display-only).

```bash
balu-code session resume abc123
```

### `balu-code session delete SESSION_ID`

```bash
balu-code session delete abc123
```

---

## config

Get or set CLI configuration values stored in `~/.config/balu-code/config.yaml`.

### `balu-code config get KEY`

```bash
balu-code config get server_url
```

### `balu-code config set KEY VALUE`

```bash
balu-code config set default_project_id 3
```

Available keys: `server_url`, `default_project_id`.
```

- [ ] **Step 3: Create `docs/config.md`**

```markdown
# Balu Code Configuration Reference

Three configuration layers, applied in order (later overrides earlier):

1. **Server defaults** — `BaluCodePluginConfig` defaults in `plugin/config.py`
2. **Persisted server config** — edited via the web UI Config tab or `PUT /config`
3. **Project-local** — `.balucode.yaml` at the project root

---

## Server config (`BaluCodePluginConfig`)

Editable in the web UI under **Balu Code → Config** or via `PUT /api/plugins/balu_code/config`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ollama_base_url` | string | `http://127.0.0.1:11434` | Ollama API base URL |
| `chat_model` | string | `qwen2.5-coder:14b-instruct-q4_K_M` | Model used for agent turns |
| `embed_model` | string | `nomic-embed-text` | Model used for RAG embeddings |
| `context_window` | int | `32768` | Token context window sent to Ollama |
| `repo_map_budget` | int | `6144` | Max tokens reserved for the repo map |
| `rag_budget` | int | `4096` | Max tokens reserved for RAG chunks |
| `rag_top_k` | int | `8` | Number of RAG chunks retrieved per turn |
| `max_iterations` | int | `12` | Max agent loop iterations per turn |
| `max_total_tokens_per_turn` | int | `80000` | Hard token cap across all iterations |
| `temperature` | float | `0.2` | Sampling temperature (0.0–2.0) |

---

## CLI config (`~/.config/balu-code/config.yaml`)

Managed via `balu-code config get/set`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `server_url` | string | `""` | BaluHost server URL |
| `default_project_id` | int \| null | `null` | Project used when no `PROJECT_ID` given |

---

## Project config (`.balucode.yaml`)

Place at the project root. All fields are optional.

```yaml
model: qwen2.5-coder:7b        # override chat_model for this project
temperature: 0.3               # override temperature
context_window: 16384          # override context_window
max_iterations: 8              # override max_iterations

auto_approve:                  # tools to auto-approve without prompting
  - read_file
  - glob
  - grep
  - repo_map

deny:                          # tools to always deny (overrides auto_approve)
  - run_bash
```

### Tool names

| Tool | Risk | Description |
|------|------|-------------|
| `read_file` | read | Read a file's contents |
| `glob` | read | List files matching a pattern |
| `grep` | read | Search file contents |
| `repo_map` | read | Get the repository structure map |
| `write_file` | write | Create or overwrite a file |
| `apply_patch` | write | Apply a unified diff |
| `run_bash` | exec | Run a shell command |
| `web_fetch` | network | Fetch a URL |
```

- [ ] **Step 4: Create `docs/CHANGELOG.md`**

```markdown
# Changelog

## v0.1.0 — 2026-04-26

First public release.

### Plugin
- FastAPI plugin for BaluHost with full agent loop (read + write tools + approval gate)
- Ollama integration with ROCm support (default: `qwen2.5-coder:14b-instruct-q4_K_M`)
- Tree-sitter repo map (Python support) + semantic RAG via `nomic-embed-text`
- Tool registry: `read_file`, `glob`, `grep`, `repo_map`, `write_file`, `apply_patch`, `run_bash`, `web_fetch`
- Per-tool approval gate: `--yolo` / `.balucode.yaml` / stored permissions / interactive
- Audit log integration (writes to BaluHost `audit_logs` table)
- WebSocket streaming chat endpoint
- Web settings panel: Models / Projects / Config / Logs tabs

### CLI
- `balu-code auth login/status` — authenticate against BaluHost
- `balu-code init` — register a project
- `balu-code models` — list available Ollama models
- `balu-code index` — start + stream an index job
- `balu-code chat` — interactive streaming chat REPL with approval flow
- `balu-code session list/resume/delete` — manage saved sessions
- `balu-code config get/set` — manage CLI configuration
```

- [ ] **Step 5: Create `docs/marketplace-submission.md`**

```markdown
# BaluHost Marketplace Submission

This is a one-time manual process performed after a successful release.

## Steps

1. **Fork** `Xveyn/BaluHost-Plugin-Market` on GitHub.

2. **Add the plugin entry** to `plugins/index.json`. Use an existing entry as a template. The required fields:

```json
{
  "name": "balu_code",
  "display_name": "Balu Code",
  "version": "0.1.0",
  "description": "Self-hosted coding agent backed by Ollama. Provides a terminal CLI and a web settings panel.",
  "author": "Xveyn",
  "category": "general",
  "homepage": "https://github.com/Xveyn/Balu_Code",
  "min_baluhost_version": "1.30.0",
  "bundle_url": "https://github.com/Xveyn/Balu_Code/releases/download/v0.1.0/balu_code-0.1.0.bhplugin",
  "checksum_sha256": "<sha256 of the .bhplugin file>"
}
```

   Compute the checksum:

   ```bash
   sha256sum dist/balu_code-0.1.0.bhplugin
   ```

3. **Open a PR** against `Xveyn/BaluHost-Plugin-Market` main with the title: `feat: add balu_code 0.1.0`.
```

- [ ] **Step 6: Commit all docs**

```bash
git add docs/install.md docs/cli.md docs/config.md docs/CHANGELOG.md docs/marketplace-submission.md
git commit -m "docs: add install, cli, config, changelog, marketplace guides"
```

---

## Task 11: Release script

**Files:**
- Create: `scripts/release.py`
- Create: `scripts/tests/test_release.py`

- [ ] **Step 1: Write failing tests**

```python
# scripts/tests/test_release.py
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def test_bump_plugin_json(tmp_path, monkeypatch):
    pj = tmp_path / "plugin.json"
    pj.write_text(json.dumps({"name": "balu_code", "version": "0.0.1", "other": "x"}))
    import scripts.release as rel
    monkeypatch.setattr(rel, "PLUGIN_JSON", pj)
    rel.bump_plugin_json("0.1.0")
    data = json.loads(pj.read_text())
    assert data["version"] == "0.1.0"
    assert data["other"] == "x"  # other fields preserved


def test_bump_pyproject(tmp_path, monkeypatch):
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[project]\nname = "balu-code-cli"\nversion = "0.0.1"\n')
    import scripts.release as rel
    monkeypatch.setattr(rel, "CLI_PYPROJECT", pp)
    rel.bump_pyproject("0.1.0")
    assert 'version = "0.1.0"' in pp.read_text()


def test_check_clean_tree_passes_on_clean(monkeypatch):
    import scripts.release as rel
    monkeypatch.setattr(rel, "run", lambda cmd, **kw: "")
    rel.check_clean_tree()  # must not raise


def test_check_clean_tree_fails_on_dirty(monkeypatch):
    import scripts.release as rel
    monkeypatch.setattr(rel, "run", lambda cmd, **kw: " M plugin/plugin.json")
    with pytest.raises(SystemExit):
        rel.check_clean_tree()


def test_version_strip_v_prefix(tmp_path, monkeypatch):
    pj = tmp_path / "plugin.json"
    pj.write_text(json.dumps({"version": "0.0.1"}))
    pp = tmp_path / "pyproject.toml"
    pp.write_text('version = "0.0.1"\n')
    import scripts.release as rel
    monkeypatch.setattr(rel, "PLUGIN_JSON", pj)
    monkeypatch.setattr(rel, "CLI_PYPROJECT", pp)
    monkeypatch.setattr(rel, "run", lambda *a, **kw: "")
    monkeypatch.setattr(rel, "check_clean_tree", lambda: None)
    with patch("sys.argv", ["release.py", "--version", "v0.1.0"]):
        rel.main()
    assert json.loads(pj.read_text())["version"] == "0.1.0"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest scripts/tests/test_release.py -v
```

Expected: `ImportError: cannot import name 'bump_plugin_json'`

- [ ] **Step 3: Create `scripts/release.py`**

```python
"""Release: bump versions, commit, tag, push.

Usage:
    python -m scripts.release --version 0.1.0
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PLUGIN_JSON = REPO_ROOT / "plugin" / "plugin.json"
CLI_PYPROJECT = REPO_ROOT / "cli" / "pyproject.toml"
CHANGELOG = REPO_ROOT / "docs" / "CHANGELOG.md"


def run(cmd: list[str], **kw) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, **kw)
    return result.stdout.strip()


def check_clean_tree() -> None:
    status = run(["git", "status", "--porcelain"])
    dirty = [ln for ln in status.splitlines() if not ln.startswith("??")]
    if dirty:
        print(f"Working tree is dirty:\n{status}", file=sys.stderr)
        sys.exit(1)


def bump_plugin_json(version: str) -> None:
    data = json.loads(PLUGIN_JSON.read_text())
    data["version"] = version
    PLUGIN_JSON.write_text(json.dumps(data, indent=2) + "\n")


def bump_pyproject(version: str) -> None:
    text = CLI_PYPROJECT.read_text()
    text = re.sub(r'^version = ".*"', f'version = "{version}"', text, flags=re.MULTILINE)
    CLI_PYPROJECT.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump version, commit, tag, push.")
    parser.add_argument("--version", required=True, help="Version string, e.g. 0.1.0 or v0.1.0")
    args = parser.parse_args()
    version = args.version.lstrip("v")

    check_clean_tree()
    bump_plugin_json(version)
    bump_pyproject(version)

    run(["git", "add", str(PLUGIN_JSON), str(CLI_PYPROJECT)])
    run(["git", "commit", "-m", f"chore(release): v{version}"])
    run(["git", "tag", f"v{version}"])
    run(["git", "push", "origin", "main", "--tags"])
    print(f"✓ Released v{version}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
pytest scripts/tests/test_release.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/release.py scripts/tests/test_release.py
git commit -m "feat(scripts): add release script with version bump + git tag"
```

---

## Task 12: CI additions

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Append `release` and `publish-cli` jobs to `.github/workflows/ci.yml`**

Add after the closing of the `test` job:

```yaml
  release:
    name: GitHub Release
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/v')
    needs: test
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v6

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"
          cache: pip

      - name: Install build deps
        run: |
          python -m pip install --upgrade pip
          pip install -e "shared[dev]"
          pip install -e "plugin[dev]"
          pip install -e "cli[dev]"
          pip install build

      - name: Build artifacts
        run: |
          python -m scripts.build_bhplugin --repo-root . --dist dist/
          python -m scripts.build_wheel --repo-root . --dist dist/

      - name: Create GitHub Release
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh release create ${{ github.ref_name }} \
            --title "Balu Code ${{ github.ref_name }}" \
            --notes-file docs/CHANGELOG.md \
            dist/*.bhplugin dist/*.whl

  publish-cli:
    name: Publish CLI to TestPyPI
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/v')
    needs: release
    steps:
      - uses: actions/checkout@v6

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"
          cache: pip

      - name: Install build + twine
        run: |
          python -m pip install --upgrade pip
          pip install -e "shared[dev]"
          pip install -e "cli[dev]"
          pip install build twine

      - name: Build wheel
        run: python -m scripts.build_wheel --repo-root . --dist dist/

      - name: Upload to TestPyPI
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.TEST_PYPI_TOKEN }}
        run: twine upload --repository testpypi dist/*.whl
```

- [ ] **Step 2: Validate YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`

- [ ] **Step 3: Run the full test suite one final time**

```bash
pytest -v && ruff check . && ruff format --check .
```

Expected: all tests PASS, ruff clean.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add release + publish-cli jobs triggered on v* tags"
```

---

## Post-plan checklist

- [ ] Add `TEST_PYPI_TOKEN` secret to the GitHub repo (`Settings → Secrets → Actions`)
- [ ] Verify `plugin/ui/bundle.js` renders correctly by sideloading the `.bhplugin` into a local BaluHost instance
- [ ] Run `python -m scripts.release --version 0.1.0` when ready to cut the first release
- [ ] Follow `docs/marketplace-submission.md` for the Plugin Market PR
