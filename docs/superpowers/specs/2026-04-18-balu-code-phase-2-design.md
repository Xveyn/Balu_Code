# Balu Code — Phase 2: Ollama Client, Project Store, Basic Routes

**Status:** Design
**Date:** 2026-04-18
**Parent spec:** [`2026-04-18-balu-code-design.md`](2026-04-18-balu-code-design.md)
**Phase 1:** complete ([plan](../plans/2026-04-18-balu-code-phase-1-foundation.md), CI green on `main`)

## Scope

Phase 2 delivers three self-contained building blocks that Phase 3 (repo-map / RAG) and Phase 4 (agent loop) depend on:

1. An **Ollama HTTP client** with streaming `chat`, `list_models`, and `embed`.
2. A **plugin-owned SQLite store** for registered projects (and an empty `repo_map_cache` table Phase 3 will populate).
3. **Five REST routes** on top of Phase 1's `/health`: project CRUD + `GET /models`.

All routes require an authenticated BaluHost user (API key or JWT), resolved by the existing `app.api.deps.get_current_user` dependency. Phase 2 is single-user: authentication is enforced, but the returned user does not scope project access (every user sees every project). Per-user scoping and audit-log emission ship later.

**Out of scope:** chat WebSocket, tool registry, repo-map extraction, RAG embeddings, UI bundle. Config schema covers only the three fields Phase 2 actually uses.

## File Structure (this phase)

```
plugin/
├── plugin.json                              [mod: no change needed — httpx+pydantic already listed]
├── __init__.py                              [mod: on_startup/on_shutdown, get_config_schema,
│                                                    get_default_config, router adds 5 routes]
├── config.py                                [new: BaluCodePluginConfig]
├── data_dir.py                              [new: resolve_data_dir()]
├── deps.py                                  [new: DI providers for ProjectStore + OllamaClient]
└── services/
    ├── __init__.py                          [new]
    ├── ollama_client.py                     [new: OllamaClient + OllamaModel]
    └── project_store.py                     [new: ProjectStore + Project models]

plugin/tests/
├── fixtures/baluhost_stub/
│   └── app/
│       ├── api/__init__.py                  [new, empty]
│       ├── api/deps.py                      [new: get_current_user stub]
│       ├── schemas/__init__.py              [new, empty]
│       └── schemas/user.py                  [new: UserPublic minimal]
├── test_config.py                           [new]
├── test_data_dir.py                         [new]
├── test_ollama_client.py                    [new: httpx.MockTransport]
├── test_project_store.py                    [new]
└── test_routes_phase2.py                    [new]
```

## Data Directory

A single resolver, used by `project_store` and (in later phases) the RAG index:

```python
# plugin/data_dir.py
def resolve_data_dir() -> Path:
    """Resolve the balu_code data directory, creating it if missing.

    Order:
      1. $BALU_CODE_DATA_DIR if set (ops/CI override)
      2. ~/.local/share/balu-code/ (XDG-ish default)
    """
```

- Calling `resolve_data_dir()` always returns an existing directory (`mkdir(parents=True, exist_ok=True)`).
- No dependency on BaluHost `settings` — there is no plugin-data-dir convention in BaluHost to integrate with.
- Phase 3 will add subdirs (e.g. `indices/`); they live under the same root.

## SQLite store

### Schema

Created idempotently on first `ProjectStore` access:

```sql
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    root_path   TEXT    NOT NULL,
    config_yaml TEXT,             -- raw .balucode.yaml blob, optional
    created_at  TEXT    NOT NULL, -- ISO-8601 UTC
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
```

`repo_map_cache` stays empty in Phase 2; it is created now so the schema is stable before Phase 3 ships.

### ProjectStore surface

```python
class Project(BaseModel):
    id: int
    name: str
    root_path: str
    config_yaml: str | None
    created_at: str
    updated_at: str

class ProjectStore:
    def __init__(self, db_path: Path): ...
    def init_schema(self) -> None: ...                          # idempotent
    def create_project(self, name: str, root_path: str,
                       config_yaml: str | None) -> Project: ... # raises DuplicateProjectError
    def list_projects(self) -> list[Project]: ...
    def get_project(self, project_id: int) -> Project: ...      # raises ProjectNotFoundError
    def delete_project(self, project_id: int) -> None: ...      # raises ProjectNotFoundError
    def close(self) -> None: ...
```

- Synchronous `sqlite3`. Async route handlers call `await asyncio.to_thread(store.method, ...)`.
- One connection per plugin instance, `check_same_thread=False` + an internal `threading.Lock`.
- Domain errors (`DuplicateProjectError`, `ProjectNotFoundError`) are mapped to 409/404 by the route layer.

## OllamaClient

```python
class OllamaModel(BaseModel):
    name: str
    size: int
    digest: str
    quantization: str | None   # from details.quantization_level
    modified_at: str | None

class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 timeout: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None): ...

    async def list_models(self) -> list[OllamaModel]: ...       # GET /api/tags
    async def embed(self, model: str, texts: list[str]) -> list[list[float]]: ...  # POST /api/embeddings
    async def chat_stream(self, model: str, messages: list[dict],
                          tools: list[dict] | None = None,
                          options: dict | None = None) -> AsyncIterator[dict]: ...  # POST /api/chat, stream=True
    async def close(self) -> None: ...
```

- `chat_stream` yields parsed NDJSON frames (`{"message": {...}, "done": bool, ...}`) one at a time. Token extraction and tool-call detection live in Phase 4's agent loop; Phase 2 only owns the parser.
- `transport` is the test injection point. Production uses the default transport; tests pass `httpx.MockTransport(handler)`.
- One retry on `httpx.ReadError`/`ConnectError` (exponential backoff, 0.5s then 1.5s); after that, raises `OllamaUnreachable`. HTTP 503 is retried once; 429 surfaces immediately as `OllamaRateLimited`.
- `OllamaTimeoutError` wraps `httpx.TimeoutException` so route-layer translation stays clean.

## Plugin config (Phase-2 subset)

```python
# plugin/config.py
class BaluCodePluginConfig(BaseModel):
    ollama_base_url: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen2.5-coder:14b-instruct-q4_K_M"
    embed_model: str = "nomic-embed-text"
```

- `BaluCodePlugin.get_config_schema()` returns `BaluCodePluginConfig`.
- `BaluCodePlugin.get_default_config()` returns `BaluCodePluginConfig().model_dump()`.
- Phase 2 reads defaults only; it does not yet consume the `installed_plugins.config` JSON that BaluHost would pass at runtime. That wiring comes when a later phase needs live overrides.

## Routes

All mounted under `/api/plugins/balu_code` (Phase 1's prefix). Every route below requires `Depends(get_current_user)`.

| Method | Path | Request | Response | Errors |
|---|---|---|---|---|
| `POST` | `/projects` | `ProjectCreate {name, root_path, config_yaml?}` | `201` `Project` | `400` invalid path, `409` name exists |
| `GET` | `/projects` | — | `200 {projects: [Project]}` | — |
| `GET` | `/projects/{id}` | — | `200 Project` | `404` |
| `DELETE` | `/projects/{id}` | — | `204` | `404` |
| `GET` | `/models` | — | `200 {models: [OllamaModel]}` | `503` if Ollama unreachable |

### Request/response shapes

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

### Validation rules

- `root_path` must be absolute (`os.path.isabs`). Relative paths → 400. Existence is **not** checked — the server may not see the same FS as the caller.
- `name` is unique across all projects.
- `config_yaml` is stored as-is; no YAML-validation in Phase 2 (parser ships with Phase 5's CLI).

## Dependency injection

Routes need access to two singletons: `ProjectStore` and `OllamaClient`. They are held in module-level globals in `plugin/deps.py` (set by `on_startup`, cleared by `on_shutdown`) and exposed to FastAPI via zero-arg dependency functions so tests can override them.

```python
# plugin/deps.py
_store: ProjectStore | None = None
_ollama: OllamaClient | None = None

def set_singletons(store: ProjectStore, ollama: OllamaClient) -> None: ...
def clear_singletons() -> None: ...

def get_project_store() -> ProjectStore:
    if _store is None: raise RuntimeError("plugin not initialized")
    return _store

def get_ollama_client() -> OllamaClient:
    if _ollama is None: raise RuntimeError("plugin not initialized")
    return _ollama
```

`BaluCodePlugin.on_startup()` constructs both instances (reading defaults from `BaluCodePluginConfig()`) and calls `set_singletons(...)`. `on_shutdown()` awaits `OllamaClient.close()` and calls `clear_singletons()`. Tests skip the lifecycle entirely by using `app.dependency_overrides[get_project_store] = lambda: fake_store`.

## BaluHost stub extension

```
plugin/tests/fixtures/baluhost_stub/app/
├── schemas/user.py       UserPublic(id, username, email, role, is_active)
├── api/deps.py           async def get_current_user() -> UserPublic:
│                              return UserPublic(...)
└── ...existing plugins/base.py unchanged...
```

`UserPublic` is a minimal Pydantic model matching the four fields the plugin reads (`id`, `username`, `email`, `role`). The stub's default `get_current_user` returns a fixed admin-like user. Tests that need a 401 path use `dependency_overrides` to substitute a dependency that raises `HTTPException(401)`.

## Test strategy

- **`test_config.py`** — defaults present, round-trip `model_dump` / `model_validate`.
- **`test_data_dir.py`** — env override, fallback path, `mkdir` idempotence; uses `monkeypatch` + `tmp_path` (never writes to the real `~`).
- **`test_ollama_client.py`** — one `httpx.MockTransport` per test. Covers: `list_models` happy path; `embed` single + batched; `chat_stream` parses a canned NDJSON sequence correctly; 503 retried once then raises; timeout mapped to `OllamaTimeoutError`; `ConnectError` → `OllamaUnreachable` after retries.
- **`test_project_store.py`** — CRUD + duplicate-name + not-found errors + idempotent `init_schema()`. Each test uses a fresh `tmp_path` DB.
- **`test_routes_phase2.py`** — FastAPI `TestClient` on a `FastAPI()` mounting the plugin router. `ProjectStore` and `OllamaClient` are replaced via `dependency_overrides`. One test per route for the happy path, plus targeted error cases (409, 404, 503). Auth is smoke-tested once: override `get_current_user` to raise 401, verify one route returns 401.

Target: **~30 new tests**, all deterministic, no network.

## CI impact

No workflow changes. Phase 2 additions are pure code under `plugin/` and `plugin/tests/`; the existing `pytest -v` step picks them up automatically. Ruff rules unchanged. Build scripts unaffected (the `.bhplugin` picks up new files via `plugin/**` glob).

## Definition of Done

- All ~30 new tests pass; total suite on `main` is >60 tests.
- `ruff check .` and `ruff format --check .` both clean.
- `python -m scripts.build_bhplugin` still succeeds; resulting `.bhplugin` contains the new modules.
- CI green on `main`.
- Manual smoke (local, optional): `pip install -e "plugin[dev]"`, start a minimal FastAPI app mounting the router with a stub `get_current_user` override, `curl -X POST /projects` with JSON body succeeds and returns 201.

## What Phase 3 will build on top

Phase 2 commits the following stable contracts that Phase 3 may assume without change:

- `ProjectStore.get_project(id)` → `Project` (Phase 3 uses `root_path` + `config_yaml` to walk the repo).
- `repo_map_cache` schema (Phase 3 only adds rows).
- `OllamaClient.embed()` signature (Phase 3 calls it for chunks).
- `resolve_data_dir()` returns a Path; Phase 3 adds `<data_dir>/indices/<project_hash>.db`.

Anything else is allowed to change.
