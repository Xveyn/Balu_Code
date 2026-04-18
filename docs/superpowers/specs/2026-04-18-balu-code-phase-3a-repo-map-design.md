# Balu Code — Phase 3a: Repo-Map (Python only)

**Status:** Design
**Date:** 2026-04-18
**Parent spec:** [`2026-04-18-balu-code-design.md`](2026-04-18-balu-code-design.md)
**Predecessor phase:** Phase 2 ([design](2026-04-18-balu-code-phase-2-design.md), [plan](../plans/2026-04-18-balu-code-phase-2-services-and-routes.md), CI green on `main`)

## Scope

Phase 3a delivers the server-side repo-map pipeline for **Python source files only** plus a structural refactor of `plugin/__init__.py`:

1. Extract `plugin/__init__.py`'s router factory and Pydantic schemas into `plugin/routes.py` and `plugin/schemas.py`. The plugin entry module shrinks to `BaluCodePlugin` + manifest load (~80 LOC).
2. Add a tree-sitter walker that parses Python files in a registered project's `root_path`, extracts top-level imports / classes / functions, and persists the result in the `repo_map_cache` table created in Phase 2.
3. Add a budget-aware text formatter that produces the Aider-style block consumed by the future agent loop.
4. Expose `GET /api/plugins/balu_code/projects/{project_id}/repo_map?budget=N` returning the rendered map plus metadata.

**Out of scope:** non-Python languages (TypeScript / Go / Rust / etc. follow as separate add-on tasks once the pipeline is proven), `.gitignore` parsing (hardcoded ignore list only), `.balucode.yaml` server-side parsing, smart ranker (alphabetical for now), real tokenization, background indexing.

## File Structure (this phase)

```
plugin/
├── __init__.py                        [shrink: only BaluCodePlugin + manifest load]
├── schemas.py                         [new: ProjectCreate, ProjectsResponse, ModelsResponse, RepoMapResponse]
├── routes.py                          [new: _build_router with all 6 Phase-2 handlers + /repo_map]
├── plugin.json                        [mod: python_requirements adds tree-sitter, tree-sitter-python]
├── requirements.txt                   [mod: same two deps]
├── pyproject.toml                     [mod: same two in dependencies]
└── services/
    ├── repo_map.py                    [new: RepoMap + render]
    └── repo_map_python.py             [new: parse_python_file]
```

`schemas.py` and `routes.py` make the plugin entry module a thin assembly point. Adding `repo_map_ts.py` / `repo_map_go.py` later is then a drop-in: the language-agnostic walker stays untouched.

## Module surface

### `plugin/services/repo_map.py`

```python
@dataclass(frozen=True)
class ClassSymbol:
    name: str
    bases: list[str]
    methods: list[str]      # rendered signatures: "def foo(self, x: int) -> str"

@dataclass(frozen=True)
class FunctionSymbol:
    name: str
    signature: str          # "def bar(x: int = 1) -> None"

@dataclass(frozen=True)
class FileSymbols:
    path: str               # POSIX-style, relative to project_root
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

class RepoMapError(Exception):
    """Base class for repo-map errors."""

class ProjectRootNotAccessible(RepoMapError):
    """Raised when the project root does not exist or is not a directory."""

class RepoMap:
    def __init__(self, project_root: Path, store: ProjectStore, project_id: int): ...
    def walk_and_cache(self) -> list[FileSymbols]: ...
    @staticmethod
    def render(files: list[FileSymbols], budget_tokens: int = 6144) -> RenderedMap: ...
```

### `plugin/services/repo_map_python.py`

```python
def parse_python_file(source: bytes) -> tuple[list[str], list[ClassSymbol], list[FunctionSymbol]]:
    """Parse Python source, return (imports, classes, top-level functions).

    Tree-sitter under the hood. On parse error returns three empty lists —
    the file's stub still appears in the repo-map but with no extracted
    symbols, so the agent at least sees the path.
    """
```

The Python parser is the only language-specific module in Phase 3a. Adding more languages = adding sibling modules with the same signature; `RepoMap` does not change.

## Cache logic (`repo_map_cache` table from Phase 2)

Schema (already in place — Phase 2 Task 5):

```sql
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

`walk_and_cache(self) -> list[FileSymbols]`:

1. Walk `project_root` honoring the hardcoded ignore list (see below). Collect every `.py` path.
2. For each path:
   - Stat for `mtime`.
   - Lookup `(project_id, relpath)` in `repo_map_cache`.
   - **Same mtime as cache** → cache hit; deserialize `symbols_json` directly.
   - **Different mtime** → compute sha1 of file contents.
     - **Same sha1 as cache** (touch without content change) → update cache `mtime` only, reuse symbols.
     - **Different sha1** → call `parse_python_file`, serialize result to JSON, upsert the row.
3. After the walk, delete any cache rows whose `file_path` was not visited (file deleted / moved).
4. Return one `FileSymbols` per visited file, in walk order (tests will sort for determinism).

Two new `ProjectStore` methods are added in Phase 3a:

```python
def upsert_repo_map_entry(
    self, project_id: int, file_path: str,
    mtime: float, sha1: str, symbols_json: str,
) -> None: ...

def list_repo_map_entries(self, project_id: int) -> list[RepoMapCacheRow]: ...

def delete_repo_map_entries(self, project_id: int, paths_to_keep: set[str]) -> None: ...
```

Plus a `RepoMapCacheRow` Pydantic model holding the five columns:

```python
class RepoMapCacheRow(BaseModel):
    project_id: int
    file_path: str
    mtime: float
    sha1: str
    symbols_json: str   # JSON-encoded (imports, classes, functions) — opaque to ProjectStore
```

All three new methods run inside the existing `threading.Lock`.

## Ignore rules (hardcoded in Phase 3a)

```python
_IGNORE_DIRS = {
    "__pycache__", ".venv", "venv", "env", "node_modules", ".git",
    ".idea", ".vscode", "dist", "build", "target",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", "htmlcov", ".tox",
}
_IGNORE_SUFFIXES = {".pyc", ".pyo", ".so"}
```

A file is included iff its name ends in `.py`, none of its path components are in `_IGNORE_DIRS`, and its suffix is not in `_IGNORE_SUFFIXES`.

`.balucode.yaml`-driven ignore is deferred to a later phase. The CLI ships its own walker in Phase 5 anyway; the server-side default is fine for the BaluHost-bundled view.

## Token budget and formatter

Phase 3a uses `len(text) // 4` as the token approximation. A real tokenizer (Ollama-side or `tiktoken`) lands in Phase 4 when the agent loop needs accuracy.

`RepoMap.render(files, budget_tokens)`:

1. Sort files alphabetically by path.
2. Render each file as an Aider-style block (see format below).
3. Append blocks one at a time, tracking cumulative `len(text) // 4`.
4. Stop appending when the next block would exceed the budget; record the dropped paths in `truncated_files`.

Format (one block per file):

```
=== plugin/services/repo_map.py (152 lines)
imports: dataclasses, pathlib, plugin.services.project_store
classes:
  class RepoMap:
    def __init__(self, project_root: Path, store: ProjectStore, project_id: int) -> None
    def walk_and_cache(self) -> list[FileSymbols]
functions:
  def helper(x: int) -> None
```

Sections (`imports:`, `classes:`, `functions:`) are omitted entirely if their list is empty (no `(none)` placeholder — keeps the prompt tight).

## Route

`GET /api/plugins/balu_code/projects/{project_id}/repo_map`

Query params:
- `budget` (int, default `6144`, min `64`, max `32768`).

Auth: `Depends(get_current_user)` like every other Phase-2 route.

Response (`RepoMapResponse`):

```json
{
  "text": "=== plugin/services/repo_map.py (152 lines)\nimports: ...\n...",
  "file_count": 17,
  "truncated_files": [],
  "total_bytes": 5980
}
```

Errors:
- `404` — `project_id` doesn't exist (translate `ProjectNotFoundError`).
- `422` — `project.root_path` doesn't exist on the server FS or is not a directory (translate `ProjectRootNotAccessible`).
- `503` — only if a future change makes the parser depend on Ollama; not used in Phase 3a.

The handler dispatches the entire walk via `await asyncio.to_thread(...)` because tree-sitter parsing is CPU-bound and the walk is I/O-bound; both are blocking.

## Refactor — Task 1

Before any new feature lands, `plugin/__init__.py` (228 lines) is split:

- `plugin/schemas.py` (new): `ProjectCreate`, `ProjectsResponse`, `ModelsResponse`, plus the new `RepoMapResponse` from this phase.
- `plugin/routes.py` (new): all 6 existing Phase-2 handlers, exported via `_build_router()`. The new `/repo_map` route is added here in a later task.
- `plugin/__init__.py` (modified): keeps only the manifest load and `BaluCodePlugin` class. `get_router()` calls `routes._build_router()`.

This refactor is purely mechanical — no behaviour change. The full Phase-2 test suite must stay at 88 passing throughout.

## Test strategy

- `test_repo_map_python.py` — parser unit tests on fixture source strings. Coverage matrix:
  - Imports: `import os`, `import os, sys`, `from app.x import Y`, `from .rel import Z`, multi-line `from x import (a, b, c)`.
  - Classes: bare, single-base, multi-base, with-decorator, with-async-method, type-annotated method signatures.
  - Functions: bare, decorated, async, with type hints, with default args.
  - Edge cases: empty file → empty result; file with syntax error → `([], [], [])` and no exception.
- `test_repo_map.py` — walker integration with `tmp_path` projects:
  - First walk populates cache.
  - Second walk on unchanged tree returns identical symbols, no parser calls (verified via parser-call counter / monkeypatch).
  - mtime drift without content change → re-stat-only path (no parse, mtime updated).
  - sha1 change → re-parse, cache updated.
  - Deleted file → cache row removed.
  - Hidden / ignored dirs are skipped.
  - `ProjectRootNotAccessible` raised when root doesn't exist.
- `test_repo_map_render.py` — formatter unit tests:
  - Empty file list → empty string + zero counts.
  - Single file rendered correctly.
  - Multiple files alphabetically sorted.
  - Budget truncation: small budget → truncated_files populated, file_count reflects only included.
  - Empty `imports`/`classes`/`functions` sections omitted.
- `test_project_store.py` (extended) — new tests for `upsert_repo_map_entry`, `list_repo_map_entries`, `delete_repo_map_entries`.
- `test_routes_repo_map.py` — full route test with fake project pointing at `tmp_path`:
  - 200 happy path with default budget.
  - 200 with explicit `?budget=` honoured.
  - 404 for unknown project.
  - 422 when `root_path` doesn't exist.
  - 401 via `dependency_overrides` (matches the Phase-2 401 smoke pattern).
- Refactor tasks (Task 1 + the route move) keep all existing route tests passing — no new behaviour.

Target: ~30 new tests, full suite at >115 passing after Phase 3a.

## New dependencies

| Package | Purpose | Approx. wheel size |
|---|---|---|
| `tree-sitter>=0.22` | Python binding to the libtree-sitter C library. | ~500 KB |
| `tree-sitter-python>=0.21` | Prebuilt Python grammar. | ~300 KB |

Added to:
- `plugin/plugin.json` `python_requirements` (BaluHost installs them on plugin enable).
- `plugin/requirements.txt` (mirror, for `pip install -r`).
- `plugin/pyproject.toml` `dependencies` (so the dev install picks them up).

The `.bhplugin` archive grows by ~1 MB. The wheel build script is unaffected — the dependencies are listed only on the plugin side, not the CLI side.

## CI impact

No workflow changes. Phase 3a additions are pure Python under `plugin/`, picked up by the existing `pytest -v` step. Ruff config unchanged. The build scripts continue to produce `.bhplugin` and `balu_code_cli` artefacts — only the `.bhplugin` content grows.

## Definition of Done

- All ~30 new tests pass; full suite >115 tests; CI green on `main`.
- `ruff check .` and `ruff format --check .` clean.
- `python -m scripts.build_bhplugin` succeeds; the resulting `.bhplugin` includes the two new `services/repo_map*.py` modules.
- `plugin/__init__.py` is back under 100 lines; `routes.py` and `schemas.py` carry the surface they should.
- Manual smoke (after sideload into BaluHost): `GET /api/plugins/balu_code/projects/{id}/repo_map` against a registered Python project returns a non-empty `text` and a sensible `file_count`.

## Carryovers into Phase 3b

- `repo_map_cache` is now actively populated; Phase 3b's RAG indexer can re-use the same walk + sha-cache logic for chunking.
- The `RepoMap` walker is single-language; Phase 3b (or a tiny intermediate task) extends it to TypeScript and Go before the agent loop ships in Phase 4.
- Token approximation `len(text) // 4` is still in use; Phase 4's agent loop replaces it with an accurate count.
- Smart ranker (recently-edited / import-weight / opened-in-chat) is still TODO; appears once Phase 5's CLI provides the "currently-opened" signal.

## What Phase 3b will build on top

- `RepoMap` chunking interface — Phase 3b adds an `iter_chunks(file_path) -> list[Chunk]` that the embedder consumes.
- New service `rag_index.py` with sqlite-vec-backed per-project DB at `<data_dir>/indices/<project_hash>.db`.
- Routes `POST /projects/{id}/index` (returns job_id) + `GET /projects/{id}/index/status`.
- Embedding pipeline using `OllamaClient.embed`.
- Top-K retrieval with keyword boost (consumed by Phase 4's context assembler).
