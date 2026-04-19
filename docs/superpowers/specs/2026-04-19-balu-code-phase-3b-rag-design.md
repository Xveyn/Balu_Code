# Balu Code — Phase 3b: RAG Indexing (Python only)

**Status:** Design
**Date:** 2026-04-19
**Parent spec:** [`2026-04-18-balu-code-design.md`](2026-04-18-balu-code-design.md)
**Predecessor phase:** Phase 3a ([design](2026-04-18-balu-code-phase-3a-repo-map-design.md), [plan](../plans/2026-04-18-balu-code-phase-3a-repo-map.md), shipped 2026-04-19 with 141 tests green)

## Scope

Phase 3b delivers the server-side RAG pipeline that Phase 4's agent loop will query for semantically-relevant code chunks:

1. A per-project `sqlite-vec` database file at `<data_dir>/indices/project_<project_id>.db` holding chunk text, metadata, and 768-dim embedding vectors.
2. A chunker that splits Python files into semantically-bounded chunks (top-level `def` / `class`), with a sliding-window fallback for long symbols and unparseable files.
3. An asynchronous indexing job exposed at `POST /projects/{id}/index` (returns 202 + `job_id`) with status polling at `GET /projects/{id}/index/status/{job_id}`.
4. A service-level `RagIndex.search(query, top_k)` API consumed by Phase 4 (no HTTP search endpoint in Phase 3b).

**Out of scope:** HTTP search route (Phase 4/5), non-Python chunking (TypeScript / Go / etc.), smart ranker (recently-edited / import-weight), live progress streaming (we poll), persistent job state across process restarts.

## File structure (this phase)

```
plugin/
├── plugin.json                          [mod: python_requirements adds sqlite-vec]
├── requirements.txt                     [mod: same]
├── pyproject.toml                       [mod: dependencies add sqlite-vec]
├── schemas.py                           [mod: +IndexJobResponse, +IndexStatusResponse]
├── routes.py                            [mod: +2 handlers]
├── deps.py                              [mod: +get_rag_registry, +get_index_job_tracker]
├── __init__.py                          [mod: on_startup constructs registry + tracker]
└── services/
    ├── repo_map.py                      [mod: promote _IGNORE_DIRS → IGNORE_DIRS (public)]
    ├── repo_map_python.py               [mod: promote _get_parser → get_parser (public)]
    ├── rag_chunker.py                   [new]
    ├── rag_index.py                     [new]
    ├── rag_registry.py                  [new: Dict[project_id -> RagIndex] lazy opener]
    └── index_jobs.py                    [new]
```

## Storage

Per-project DB at `<data_dir>/indices/project_<project_id>.db`. Each file is self-contained; the `project_id` is in the filename (not in every row) so we can drop an index by deleting one file.

Schema, created idempotently on first `RagIndex.open()`:

```sql
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT NOT NULL,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    text        TEXT NOT NULL,
    file_sha1   TEXT NOT NULL,
    embedded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_path);

-- Virtual table provided by sqlite-vec. `rowid` aligns with `chunks.id`.
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(embedding float[768]);
```

Inserts use an explicit pair of statements bound by the shared id, inside a `BEGIN IMMEDIATE` transaction:

```sql
BEGIN IMMEDIATE;
INSERT INTO chunks (file_path, start_line, end_line, text, file_sha1, embedded_at)
  VALUES (?, ?, ?, ?, ?, ?);
-- use last_insert_rowid() as the id
INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?);
COMMIT;
```

## Module surface

### `plugin/services/rag_chunker.py` (pure, no side effects)

```python
@dataclass(frozen=True)
class Chunk:
    file_path: str
    start_line: int    # 1-indexed, inclusive
    end_line: int      # inclusive
    text: str


def chunk_python_file(
    file_path: str,
    source: bytes,
    *,
    window_lines: int = 40,
    overlap_lines: int = 10,
    symbol_max_lines: int = 80,
) -> list[Chunk]:
    """Split a Python file into chunks for embedding.

    Strategy:
      1. Tree-sitter parse the file. For each top-level class/function:
         - If the symbol spans <= symbol_max_lines → one chunk covering
           the full span (including decorators and class body).
         - Otherwise → sliding windows of ``window_lines`` with
           ``overlap_lines`` overlap, covering the symbol's line range.
      2. Module-level lines before the first top-level symbol (imports,
         module docstring, constants) are grouped into a single
         "prologue" chunk. Lines between top-level symbols are treated
         the same way — one inter-symbol chunk per gap of > 0 lines.
      3. If the parser finds no top-level symbols (empty file, syntax
         error, pure module-level code) → sliding windows over the
         entire file.
      4. Each chunk's ``text`` is the raw bytes decoded UTF-8 with
         ``errors='replace'``.
    """
```

The tree-sitter parser is reused from `repo_map_python.py` by promoting its existing private `_get_parser()` helper to public `get_parser()`. The chunker imports `get_parser` and walks the tree itself to pull `(node.start_point[0], node.end_point[0])` for each top-level `class_definition` / `function_definition` / `decorated_definition` — the existing `parse_python_file` returns signatures, not line ranges, so the chunker has its own lightweight walk. No new parser instance is created; the module-level singleton in `repo_map_python.py` is shared.

### `plugin/services/rag_index.py`

```python
class RagIndexError(Exception):
    """Base class for RAG-index errors."""

class RagIndexUnavailable(RagIndexError):
    """Raised when sqlite-vec extension fails to load."""


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float  # cosine similarity (0..1) with optional keyword boost applied


class RagIndex:
    """Per-project sqlite-vec store.

    A single instance per project, lazily opened by the registry.
    Thread-confined — caller must wrap blocking operations in
    ``asyncio.to_thread``.
    """

    def __init__(
        self,
        db_path: Path,
        embed_model: str,
        ollama: OllamaClient,
        vector_dim: int = 768,
    ) -> None: ...

    async def open(self) -> None:
        """Open the DB, load sqlite-vec, run CREATE TABLE IF NOT EXISTS.

        Raises RagIndexUnavailable if sqlite-vec cannot load.
        """

    async def close(self) -> None: ...

    async def upsert_file_chunks(
        self, file_path: str, file_sha1: str, chunks: list[Chunk]
    ) -> None:
        """Replace this file's chunks atomically.

        Deletes existing rows for ``file_path`` (in both ``chunks`` and
        ``vec_chunks``), embeds each new chunk via OllamaClient.embed,
        and inserts the rows in a transaction.
        """

    async def delete_file_chunks(self, file_path: str) -> None: ...

    async def get_file_sha1(self, file_path: str) -> str | None:
        """Return the sha1 stored for this file, or None if unindexed.

        Uses the first chunk's sha1; every chunk for a file shares the
        same file_sha1.
        """

    async def all_indexed_paths(self) -> set[str]:
        """All distinct file_path values. Used for cleanup of deleted files."""

    async def search(
        self, query: str, top_k: int = 8, *, keyword_boost: float = 0.15
    ) -> list[SearchHit]:
        """Top-K nearest chunks with optional keyword boost.

        Embeds the query once, fetches top ``top_k * 2`` via sqlite-vec,
        computes ``base_score = 1 - distance``, adds ``keyword_boost``
        when any query token (case-insensitive word split on
        non-alphanumerics) appears in ``file_path`` or ``chunk.text``,
        sorts descending, returns top ``top_k``.
        """
```

Instantiation rule: one `RagIndex` per project, shared across requests. The registry (next) owns them.

### `plugin/services/rag_registry.py`

```python
class RagRegistry:
    """Lazy Dict[project_id -> RagIndex]. Opens on first use; closes in bulk on plugin shutdown."""

    def __init__(
        self, data_dir: Path, embed_model: str, ollama: OllamaClient
    ) -> None: ...

    async def get(self, project_id: int) -> RagIndex:
        """Return the (opened) RagIndex for this project, creating + opening if needed."""

    async def close_all(self) -> None: ...
```

Rationale for a separate registry instead of putting it on the plugin class: tests can swap in a `FakeRagRegistry` via FastAPI `dependency_overrides` the same way `get_project_store` is overridden in Phase-2/3a tests.

### `plugin/services/index_jobs.py`

```python
class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class IndexJob:
    id: str
    project_id: int
    status: JobStatus
    files_total: int = 0
    files_processed: int = 0
    chunks_total: int = 0
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class AlreadyIndexingError(Exception):
    """Raised by start_job when a job for the same project is still running."""


class IndexJobTracker:
    """Per-process in-memory registry of indexing jobs.

    Jobs are keyed by UUID; a secondary map tracks per-project running
    status so concurrent POSTs on the same project can be rejected with
    409. No persistence: on process restart the state is lost, but
    indexed data survives in sqlite-vec.
    """

    def __init__(self) -> None: ...

    def start_job(
        self,
        project_id: int,
        worker: Callable[[IndexJob], Awaitable[None]],
    ) -> IndexJob:
        """Create an IndexJob, spawn worker as asyncio.Task, return job.

        Worker signature: ``async def worker(job: IndexJob) -> None``.
        Worker owns updating ``job.status`` / ``files_*`` / ``chunks_*``
        / ``error`` fields. The tracker wraps the task to move status to
        DONE / ERROR on completion, whichever the worker didn't set
        explicitly.

        Raises AlreadyIndexingError if the same project_id already has
        a QUEUED or RUNNING job.
        """

    def get_job(self, job_id: str) -> IndexJob | None: ...

    def is_running_for_project(self, project_id: int) -> bool:
        """True when any QUEUED or RUNNING job for project_id exists."""
```

## Indexing worker flow

When `POST /projects/{id}/index` triggers a job, the worker runs:

```
async def _run_index_job(job: IndexJob, project: Project, rag: RagIndex):
    job.status = RUNNING
    job.started_at = now_iso()

    # 1. Walk the project root honouring IGNORE_DIRS from repo_map.py.
    seen_paths: set[str] = set()
    files_to_process: list[tuple[str, bytes, str]] = []
    for fs_path, rel_posix in _iter_python_files(project_root):
        seen_paths.add(rel_posix)
        content_bytes = fs_path.read_bytes()
        sha1 = hashlib.sha1(content_bytes).hexdigest()
        cached_sha1 = await rag.get_file_sha1(rel_posix)
        if cached_sha1 == sha1:
            continue  # skip: content unchanged
        files_to_process.append((rel_posix, content_bytes, sha1))

    job.files_total = len(files_to_process)

    # 2. Chunk + embed + upsert per file.
    for rel_posix, content_bytes, sha1 in files_to_process:
        chunks = chunk_python_file(rel_posix, content_bytes)
        await rag.upsert_file_chunks(rel_posix, sha1, chunks)
        job.files_processed += 1
        job.chunks_total += len(chunks)

    # 3. Drop chunks for files that disappeared.
    indexed_paths = await rag.all_indexed_paths()
    for stale_path in indexed_paths - seen_paths:
        await rag.delete_file_chunks(stale_path)

    job.status = DONE
    job.finished_at = now_iso()
```

Errors during the walk / chunk / embed raise through the worker; the tracker's wrapper catches them and sets `job.status = ERROR`, `job.error = str(exc)`.

`_iter_python_files(root)` is a small module-level helper added to `plugin/services/rag_index.py` (or a shared file-walker module if we want to deduplicate with Phase 3a's `RepoMap` — for v1 we accept slight duplication since `RepoMap` uses `os.walk` internally and Phase 3b's indexer needs the same shape). Shared: `IGNORE_DIRS` (promoted to public in `repo_map.py`).

## Routes

### `POST /projects/{project_id}/index`

Body: — (empty).

Response: `202 Accepted` + `IndexJobResponse`:

```python
class IndexJobResponse(BaseModel):
    job_id: str
    status: JobStatus   # always QUEUED at response time
    project_id: int
```

Errors:
- `404` — project not found.
- `409` — job already queued/running for this project (`AlreadyIndexingError`).
- `503` — `RagIndexUnavailable` (sqlite-vec failed to load).

### `GET /projects/{project_id}/index/status/{job_id}`

Response: `200` + `IndexStatusResponse`:

```python
class IndexStatusResponse(BaseModel):
    job_id: str
    project_id: int
    status: JobStatus
    files_total: int
    files_processed: int
    chunks_total: int
    error: str | None
    started_at: str | None
    finished_at: str | None
```

Errors:
- `404` — job id unknown OR its project_id doesn't match the URL path (prevents status disclosure across projects).

Both routes require `Depends(get_current_user)`.

## Plugin lifecycle integration

`BaluCodePlugin.on_startup`:
- Existing: resolve data_dir, construct ProjectStore, construct OllamaClient.
- New: construct `RagRegistry(data_dir, config.embed_model, ollama)` and `IndexJobTracker()`. Register both with `set_singletons` (extend signature).

`BaluCodePlugin.on_shutdown`:
- Existing: close ollama, close store, clear singletons.
- New: `await registry.close_all()` before clearing.

`plugin/deps.py` gains `get_rag_registry()` and `get_index_job_tracker()` module-level getters.

## Search semantics

`RagIndex.search("handle authentication errors", top_k=8)`:

1. `query_vec = (await self._ollama.embed(self._embed_model, [query]))[0]`.
2. Fetch top-`2*top_k` candidates from sqlite-vec:
   ```sql
   SELECT chunks.file_path, chunks.start_line, chunks.end_line, chunks.text,
          vec_chunks.distance
     FROM vec_chunks
     JOIN chunks ON chunks.id = vec_chunks.rowid
    WHERE vec_chunks.embedding MATCH :query_vec
      AND k = :k_over
    ORDER BY vec_chunks.distance
   ```
3. Per candidate: `base_score = 1 - distance`. Tokens := `query.lower()` split on `\W+`, filtered to `len >= 3`. If any token ∈ `file_path.lower()` or `chunk.text.lower()` → `score = base_score + keyword_boost` (default 0.15), else `score = base_score`.
4. Sort hits by `-score`, return first `top_k` as `list[SearchHit]`.

## Test strategy

- **`test_rag_chunker.py`** — pure-function unit tests, no DB, no network:
  - Small file with one short `def` → one chunk covering the def.
  - File with `def` > 80 lines → multiple overlapping windows.
  - File with two adjacent classes → prologue + two chunks + (possibly) gap chunk.
  - Empty file → empty list.
  - File with only syntax error → sliding windows over bytes.
  - File with imports only, no symbols → one chunk.
  - Chunk line numbers are 1-indexed and contiguous-inclusive.

- **`test_rag_index.py`** — integration against real `sqlite-vec` in `tmp_path`, with a `_FakeOllama` that returns deterministic 768-dim vectors (e.g. hashed text → seeded numpy):
  - `open` creates the schema idempotently.
  - `upsert_file_chunks` inserts N chunks; `all_indexed_paths` returns the file; `get_file_sha1` returns the stored sha1.
  - Second `upsert_file_chunks` for the same path replaces rows (no duplicates).
  - `delete_file_chunks` removes both table and vec rows.
  - `search` returns top-K in distance order.
  - `search` keyword boost: query contains a token from `file_path` → that chunk ranks higher than an equally-similar one without the token.
  - `RagIndexUnavailable` path: mock `sqlite_vec.load` to raise → `open` raises `RagIndexUnavailable`.

- **`test_index_jobs.py`** — lifecycle + concurrency:
  - `start_job` creates a QUEUED job, worker transitions to RUNNING then DONE.
  - Second `start_job` for the same project while first is running → `AlreadyIndexingError`.
  - Worker raising → job ends in ERROR with captured message.
  - `get_job` returns None for unknown id.
  - Multiple projects can run concurrently (two `start_job` calls with different project_ids).

- **`test_routes_index.py`** — full route tests with dependency overrides; the `rag` dependency returns a `FakeRagRegistry` whose `get(project_id)` hands back an in-memory `RagIndex` opened against `tmp_path`:
  - `POST` on unknown project → 404.
  - `POST` happy path → 202 with `job_id`; polling transitions to DONE.
  - Second `POST` while first running → 409.
  - `GET /status/{unknown_id}` → 404.
  - `GET /status/{known_id}` for wrong project_id → 404 (cross-project info disclosure guard).
  - Auth 401 via `dependency_overrides[get_current_user]` raising.

Target: **~32 new tests**. Full suite ≥ 173 after Phase 3b.

## New dependencies

| Package | Purpose | Size |
|---|---|---|
| `sqlite-vec>=0.1.9` | SQLite extension loader for vector search. | ~500 KB |

Added to `plugin/plugin.json` `python_requirements`, `plugin/requirements.txt`, `plugin/pyproject.toml` `dependencies`.

## Definition of Done

- All ~32 new tests pass locally; full suite ≥ 173.
- CI green on Python 3.11 + 3.12.
- `ruff check .` and `ruff format --check .` clean.
- `.bhplugin` archive contains `services/rag_chunker.py`, `services/rag_index.py`, `services/rag_registry.py`, `services/index_jobs.py`.
- Happy-path smoke against a tmp fixture project: `POST /index` returns 202, polling reaches `DONE` with `chunks_total > 0`, `RagIndex.search()` returns hits that include the expected file paths.

## Carryovers into Phase 4

- Agent loop calls `RagIndex.search(query, top_k)` as a blocking operation wrapped in `asyncio.to_thread`. Budget-aware trim of the returned chunks into the prompt is Phase 4's concern (this phase just returns top-K).
- Live progress streaming for long indexing jobs (instead of polling) is a v2 concern.
- A `GET /projects/{id}/search?q=...` route for CLI debugging may be added in Phase 4/5.
- Multi-language chunkers (TypeScript, Go, Rust) drop in as sibling `rag_chunker_ts.py` etc. once Phase 4 proves the Python path.
- Smart ranker (recently-edited / import-weight / opened-in-chat) layers on top of `search` once Phase 5's CLI feeds "currently-opened" hints.

## What Phase 4 will build on top

- `RagIndex.search()` surface is frozen after this phase.
- The agent loop's context assembler (Phase 4) orders: system prompt → tool-use instructions → repo_map (Phase 3a) → RAG chunks (this phase) → session history → user message.
- Tokenization accuracy work (replacing `len(text) // 4`) happens in Phase 4 alongside the first real prompt construction.
