# Balu Code — Repo-Map (OpenCode-Reboot)

**Status:** Design
**Date:** 2026-05-16
**Supersedes (target architecture):** [`2026-04-18-balu-code-phase-3a-repo-map-design.md`](2026-04-18-balu-code-phase-3a-repo-map-design.md) — same data model, new integration point
**Related:** [`2026-04-27-js-ts-indexing-design.md`](2026-04-27-js-ts-indexing-design.md) (multi-language parser layout reused), [`2026-05-14-opencode-runtime-integration-design.md`](2026-05-14-opencode-runtime-integration-design.md) (current runtime architecture)

## Goal

Inject a token-budgeted, structural overview of the user's project into every chat turn so the agent (qwen2.5-coder via OpenCode) starts with grounded knowledge of what files and symbols exist — without spending Read/Grep/Glob round-trips on discovery.

The motivating problem: `plugin/prompts/system.md` already promises the model a *"repository map showing top-level symbols"*, but no code in the plugin produces or sends one. The Phase 3a design that originally addressed this targeted a Balu-Code-owned agent loop that no longer exists; the OpenCode switch (2026-05-14) made the integration point obsolete. This spec retargets the same feature to OpenCode's `POST /session/{id}/message` API.

## Non-goals

- Semantic chunk retrieval (RAG). The system.md promise of *"semantically-retrieved chunks"* is dropped from V1; we will revise system.md to reflect what we actually deliver. RAG returns as a follow-up phase only if the structural map proves insufficient in practice.
- Languages beyond Python, JavaScript, TypeScript, JSX, TSX. Rust/Go/Java land in a follow-up if asked.
- PageRank-style symbol-graph weighting. Phase 3a's original alphabetical ranker is sufficient for v1 token budgets (≤8k). PageRank moves to a follow-up if budget pressure justifies the complexity.
- `.gitignore` parsing or user-configurable ignore lists. The hardcoded list is enough for V1; extending it is a follow-up if a real project hits a gap.
- A dedicated UI for browsing the map. The map is an internal context-assembly artefact, not a user-facing view. (A debug endpoint to dump the current map exists — see Routes.)
- Background indexing service. Indexing runs synchronously on the chat hot path, gated by mtime cache so steady-state cost is near zero.

## Scope

| Component | State today | Action |
|---|---|---|
| DB table `repo_map_cache` | Created (Phase 2) | Reuse as-is |
| `ProjectStore.upsert_repo_map_entry` / `list_repo_map_entries` / `delete_repo_map_entries` | Implemented + tested | Reuse as-is |
| `RepoMapCacheRow` Pydantic row | Implemented | Reuse as-is |
| `BaluCodePluginConfig.repo_map_budget` | `6144` default | Lower default to `2048` |
| `plugin/services/parsers/` | Empty folder (`__pycache__` only) | Add `python.py`, `js_ts.py`, `__init__.py` |
| `plugin/services/repo_map.py` | Does not exist | Add `RepoMap`, `RenderedMap`, render() |
| `plugin/services/tools/` | Empty folder | Leave for follow-up tool-use phase |
| `plugin/routes.py` `/chat/v2/{project_id}` | Sends only the raw user text | Prepend the rendered repo-map block to the user message text |
| `plugin/routes.py` debug routes | None for repo-map | Add `GET .../repo_map` and `POST .../repo_map/rebuild` |
| `plugin/prompts/system.md` | Dead file, references unimplemented features | Either delete or repurpose; see "system.md drift" below |
| `plugin/plugin.json` + `requirements.txt` + `pyproject.toml` | No tree-sitter deps | Add `tree-sitter`, `tree-sitter-python`, `tree-sitter-javascript`, `tree-sitter-typescript` |

## Architectural decisions

### Integration point: prepend to user-message text

OpenCode v1.14.50's `POST /session/{id}/message` accepts only `parts[].text` and `model.{providerID, modelID}`. There is no dedicated `system_prompt` field. OpenCode auto-discovers `AGENTS.md` walking up from the server's CWD; we deliberately do **not** write to the user's `AGENTS.md` because that file belongs to the user and may already exist with project-specific instructions.

Instead, we prepend a clearly delimited block to the `text` argument in `OpencodeClient.prompt()`:

```text
<repo_map project="balu-code" generated="2026-05-16T10:23:04Z" budget="2048" files="17">
=== plugin/services/opencode_runtime.py (394 lines)
imports: asyncio, fcntl, hashlib, httpx, ...
classes:
  class ServerHandle:
    def pid(self) -> int
    def owned(self) -> bool
  class Watchdog:
    def run(self) -> None
functions:
  def detect_target_triple() -> str
  async def ensure_binary(data_dir: Path) -> Path
  async def start_server(...) -> ServerHandle
...
</repo_map>

<user_message>
[the user's actual message]
</user_message>
```

**Why this works for token caching:** OpenCode + Ollama see a stable prefix (the repo-map block) followed by a variable suffix (the user's message). KV-cache hits the prefix until the index changes. The cost of "re-sending the map every turn" is amortised by cache hits — same model behaviour as if it were in a system prompt.

**Why this beats writing AGENTS.md:** zero touch on the user's repo. The user's `AGENTS.md`, if present, still gets discovered by OpenCode and combined with our prepended block.

**Why this beats a tool the model calls:** qwen2.5-coder's tool-use stamina is limited; making it call `get_repo_map` before every task adds the very round-trip we want to remove.

### Data model: reuse Phase 2's `repo_map_cache`

Schema (already in `project_store.py:61`):

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

The `symbols_json` payload is opaque to `ProjectStore` — `RepoMap` is the only consumer. The JSON schema is:

```json
{
  "lines": 394,
  "imports": ["asyncio", "fcntl", "hashlib", "httpx"],
  "classes": [
    {"name": "ServerHandle", "bases": [], "methods": ["def pid(self) -> int", "def owned(self) -> bool"]},
    {"name": "Watchdog", "bases": [], "methods": ["async def run(self) -> None"]}
  ],
  "functions": [
    {"name": "detect_target_triple", "signature": "def detect_target_triple() -> str"},
    {"name": "ensure_binary", "signature": "async def ensure_binary(data_dir: Path) -> Path"}
  ],
  "v": 1
}
```

The `"v"` field exists so a future schema change can invalidate stale rows by version mismatch without dropping the table.

### Walk + cache logic

`RepoMap.walk_and_cache(self) -> list[FileSymbols]`:

1. Resolve `project.root_path` from `ProjectStore`. Raise `ProjectRootNotAccessible` if missing or not a directory.
2. Walk the tree, honouring the hardcoded ignore set (below). Collect supported source paths.
3. For each path:
   - Stat for `mtime`.
   - Look up `(project_id, relpath)` in `repo_map_cache`.
   - **Cache hit (same mtime):** deserialise `symbols_json`. No parse.
   - **mtime drift:** compute sha1 of contents.
     - **Same sha1:** update only `mtime` in cache; reuse symbols.
     - **Different sha1:** dispatch to language-specific parser, serialise, upsert.
4. After the walk, call `delete_repo_map_entries(project_id, paths_to_keep)` so deleted/moved files vanish from cache.
5. Return `[FileSymbols]` for the visited files.

### Parser dispatch

The 2026-04-27 spec already established the module shape; we ship both languages at once because the structure is identical:

```
plugin/services/parsers/
  __init__.py        # re-exports parse_file(source: bytes, extension: str)
  python.py          # parse_python_file(source: bytes) -> (imports, classes, functions)
  js_ts.py           # parse_js_ts_file(source: bytes, extension: str) -> (imports, classes, functions)
```

Extension dispatch lives in `parsers/__init__.py:parse_file(source, ext)`. Adding a language = adding a sibling module + one entry in the dispatch table.

Tree-sitter parsers are lazy singletons (constructed once per process, reused per call).

### Render + budget

`RepoMap.render(files, budget_tokens) -> RenderedMap`:

1. Sort `files` alphabetically by relative path.
2. Render each file as a block (format above).
3. Accumulate `len(text) // 4` as the token estimate. Stop appending when the next block would exceed the budget.
4. Record dropped paths in `truncated_files`.
5. Emit the surrounding `<repo_map …>` envelope with metadata.

Sections (`imports:`, `classes:`, `functions:`) are omitted when their list is empty — no `(none)` placeholders. The format follows the Aider convention so existing literature about prompt assembly carries over.

`len(text) // 4` is sufficient for V1 and matches what Phase 3a designed. A real tokenizer is a follow-up only if the budget proves loose under qwen-coder.

### Ignore rules (hardcoded)

```python
_IGNORE_DIRS = frozenset({
    "__pycache__", ".venv", "venv", "env", "node_modules", ".git",
    ".idea", ".vscode", "dist", "build", "target", "out",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", "htmlcov", ".tox",
    ".next", ".nuxt", ".turbo", "coverage",
})
_SOURCE_EXTENSIONS = frozenset({".py", ".js", ".jsx", ".ts", ".tsx"})
_IGNORE_SUFFIXES = frozenset({".pyc", ".pyo", ".so", ".min.js", ".d.ts"})
```

A file is included iff `Path(name).suffix in _SOURCE_EXTENSIONS`, none of its path parts are in `_IGNORE_DIRS`, and its name does not end with anything in `_IGNORE_SUFFIXES`.

User-configurable ignores are out of scope for V1; deferred until someone hits a real case.

## Module surface

### `plugin/services/repo_map.py`

```python
@dataclass(frozen=True)
class ClassSymbol:
    name: str
    bases: list[str]
    methods: list[str]      # full signatures: "async def foo(self, x: int) -> str"

@dataclass(frozen=True)
class FunctionSymbol:
    name: str
    signature: str

@dataclass(frozen=True)
class FileSymbols:
    path: str               # POSIX, relative to project_root
    lines: int
    imports: list[str]
    classes: list[ClassSymbol]
    functions: list[FunctionSymbol]

@dataclass(frozen=True)
class RenderedMap:
    text: str               # the full envelope, ready to prepend
    file_count: int
    truncated_files: list[str]
    total_bytes: int

class RepoMapError(Exception): ...
class ProjectRootNotAccessible(RepoMapError): ...

class RepoMap:
    def __init__(
        self,
        project_root: Path,
        store: ProjectStore,
        project_id: int,
    ) -> None: ...
    def walk_and_cache(self) -> list[FileSymbols]: ...
    @staticmethod
    def render(
        files: list[FileSymbols],
        *,
        budget_tokens: int = 2048,
        project_name: str = "",
    ) -> RenderedMap: ...
```

### `plugin/services/parsers/__init__.py`

```python
def parse_file(source: bytes, extension: str) -> tuple[
    list[str], list[ClassSymbol], list[FunctionSymbol]
]:
    """Dispatch to the right language parser. Unknown extension → ([],[],[])."""
```

### Wire-up in `routes.py:/chat/v2/{project_id}`

Current call site (routes.py:272-278):

```python
result = await client.prompt(
    session_id,
    text=last_user.content,
    model_provider=provider,
    model_id=model_id,
)
```

New:

```python
project = get_project_store().get_project(project_id)
config = get_plugin_config()
repo_map_text = ""
if config.repo_map_enabled:
    repo_map = RepoMap(Path(project.root_path), get_project_store(), project_id)
    try:
        files = await asyncio.to_thread(repo_map.walk_and_cache)
        rendered = RepoMap.render(
            files,
            budget_tokens=config.repo_map_budget,
            project_name=project.name,
        )
        repo_map_text = rendered.text
    except ProjectRootNotAccessible:
        repo_map_text = ""  # silently degrade — chat still works

prompt_text = f"{repo_map_text}\n\n<user_message>\n{last_user.content}\n</user_message>" if repo_map_text else last_user.content

result = await client.prompt(
    session_id,
    text=prompt_text,
    model_provider=provider,
    model_id=model_id,
)
```

`asyncio.to_thread` because tree-sitter parsing and stat I/O block. The full walk on steady-state (all cache hits) is ~10ms per 100 files; uncached parsing is ~5ms per file.

### Debug routes

For visibility and ops control, add two routes to `routes.py`:

```
GET  /api/plugins/balu_code/projects/{project_id}/repo_map?budget=N
POST /api/plugins/balu_code/projects/{project_id}/repo_map/rebuild
```

- `GET` returns `RepoMapResponse {text, file_count, truncated_files, total_bytes}` so Sven can inspect what the model actually sees.
- `POST .../rebuild` deletes the project's cache rows and forces a full re-walk on next chat turn. Useful when changing parsers or schema.

Both authenticated via the same `get_current_user` pattern as the other Phase-2 routes.

### Config changes

`BaluCodePluginConfig`:

- `repo_map_budget: int = 2048` (was `6144`). 2k is enough for the qwen-coder 14b context window of 32k while leaving room for conversation, tools, and reply. Re-tunable from the UI.
- `repo_map_enabled: bool = True` — emergency off-switch if the map confuses the model.
- (`embed_model`, `rag_budget`, `rag_top_k` stay as-is, untouched — they remain placeholders for a future RAG phase.)

## system.md drift

`plugin/prompts/system.md` currently says:

> Every turn you are given:
> - A repository map showing top-level symbols from each Python file in the project.
> - Semantically-retrieved chunks of code that match the user's question.

The file is never read by any Python code today. Two options:

**(a) Delete it** and drop the prompts/ folder entirely. The system prompt already comes from OpenCode's defaults + any `AGENTS.md` the user maintains.

**(b) Repurpose it** into the project's `AGENTS.md`-style instructions, which Balu Code maintains for the user's workspace.

For V1, **delete it** (option a). It's dead weight that misleads future contributors about how the system works. If we later want project-level instructions in addition to the prepended map, we ship that as a separate, deliberate feature.

The `prompts/tool_use.md` file is also untouched by code — same treatment.

## Test strategy

Mirroring the Phase 3a + 2026-04-27 test design, scaled to the merged scope:

- `test_repo_map_python.py` — parser unit tests on fixture source strings, covering bare/decorated/async/typed functions, single/multi-base/decorated classes, multi-line imports, edge cases (empty file, syntax error → empty tuples without raising).
- `test_repo_map_js_ts.py` — parser unit tests for `function_declaration`, `class_declaration`, `interface_declaration`, `type_alias_declaration`, arrow-function `lexical_declaration`, `export_statement` unwrapping. Both JS and TS grammars covered; JSX/TSX share the same parsers.
- `test_repo_map.py` — walker integration:
  - First walk populates cache; second walk hits cache (parser-call counter).
  - mtime drift, same content → re-stat-only path.
  - sha1 drift → re-parse.
  - Deleted file → cache row removed.
  - Hidden / ignored dirs skipped.
  - `ProjectRootNotAccessible` when root missing.
  - Mixed-language project (Python + TS) routes to correct parsers.
- `test_repo_map_render.py` — render unit tests:
  - Empty file list → envelope with `file_count=0`.
  - Files sorted alphabetically.
  - Budget truncation populates `truncated_files`.
  - Empty sections (`imports:`, `classes:`, `functions:`) omitted entirely.
  - Envelope contains `<repo_map …>` opening tag with metadata attrs.
- `test_routes_chat_v2_repo_map.py` — integration: chat call with a registered tmp_path project produces a `prompt_text` that contains the rendered map envelope before the user message. Cover the `repo_map_enabled=False` path and the silent-degrade-on-`ProjectRootNotAccessible` path.
- `test_routes_repo_map_debug.py` — `GET /repo_map` happy path + `?budget=`; `POST /repo_map/rebuild` clears cache; 404 unknown project; 422 inaccessible root; 401 unauthenticated.

Target: ~40 new tests; full suite remains green.

## New dependencies

| Package | Purpose | Approx. wheel size |
|---|---|---|
| `tree-sitter>=0.22` | Python binding to libtree-sitter | ~500 KB |
| `tree-sitter-python>=0.21` | Python grammar | ~300 KB |
| `tree-sitter-javascript>=0.23` | JS/JSX grammar | ~400 KB |
| `tree-sitter-typescript>=0.23` | TS/TSX grammar | ~500 KB |

Added to `plugin/plugin.json` `python_requirements`, `plugin/requirements.txt`, and `plugin/pyproject.toml` `dependencies`. The `.bhplugin` archive grows by ~2 MB; no script changes needed.

**Note on the unmaintained `tree-sitter-languages`:** we use the individual grammar packages, not the abandoned aggregator. `tree-sitter-language-pack` would also work but adds 300+ unused grammars; skipped for size.

## Prod deployment via symlink

The plugin is already symlinked into prod: `/opt/baluhost/backend/app/plugins/installed/balu_code → /home/sven/projects/plugins/Balu_Code/plugin`. This means:

- New `services/repo_map.py` and `services/parsers/*.py` are picked up on next BaluHost backend restart — no `.bhplugin` rebuild needed for dev iteration.
- `python_requirements` additions in `plugin.json` are installed by BaluHost's plugin manager on plugin enable; for the live install Sven runs `pip install tree-sitter tree-sitter-python tree-sitter-javascript tree-sitter-typescript` into the BaluHost backend venv once, then restarts.
- Tests in `plugin/tests/` run against the symlinked module via the existing `pytest -v` step — same as today.

No special prod-vs-dev handling needed in code; the symlink makes them identical.

## Performance budget

For a Balu Code-sized project (~10k LOC, ~80 files):

- **Cold walk (no cache):** ~400ms (mostly parse).
- **Warm walk (all cache hits):** ~30ms (stat-only).
- **Per-turn cost on chat hot path:** negligible (single `to_thread` round-trip).
- **Map size at 2k budget:** ~8 KB of text.

For a larger workspace (50k LOC, ~500 files) the warm walk is ~200ms — still acceptable per chat turn. If this becomes a problem in practice, the optimisation is to skip the walk on consecutive turns within a short window (cache the rendered map for N seconds).

## Definition of done

- All new tests pass (~40 added). Full suite green on CI.
- `ruff check .` and `ruff format --check .` clean.
- `python -m scripts.build_bhplugin` succeeds; resulting `.bhplugin` contains `services/repo_map.py` and `services/parsers/`.
- Manual smoke against the symlinked prod install:
  - `GET /api/plugins/balu_code/projects/{id}/repo_map` returns a non-empty `text` with `<repo_map ...>` envelope.
  - A chat turn through `/chat/v2/{id}` sees the map prepended (verified via audit log or by inspection of the assembled prompt).
  - The model's first response demonstrates awareness of repo structure (e.g. references a symbol it would have had to grep for previously).
- `plugin/prompts/` deleted (both `system.md` and `tool_use.md`).

## Carryovers / follow-ups

- **RAG (chunk retrieval)** — system.md's second promise. Revisit after using the repo-map for a week; ship only if the gap is felt.
- **PageRank ranker** — only if a 2k budget is clearly truncating important symbols across many projects.
- **Real tokenizer** — when `len // 4` proves loose under qwen-coder, swap in a model-specific counter.
- **User-configurable ignores** — when a real project hits a directory the hardcoded list misses.
- **Background indexer** — only if hot-path indexing becomes user-visible latency.
- **Tool-use refresh** — expose `get_repo_map` as an OpenCode tool so the model can pull a fresh map mid-turn after editing files. Folds into a broader tools/ phase later.
