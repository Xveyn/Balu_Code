# Balu Code — Phase 3b: RAG Indexing (Python only)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-project `sqlite-vec` index built by an asynchronous `POST /projects/{id}/index` job (polled via `GET /index/status/{job_id}`) and a `RagIndex.search(query, top_k)` service-level API ready for Phase 4's agent loop to consume.

**Architecture:** A per-project `sqlite-vec` DB file holds chunk text + 768-dim embeddings keyed by `(project_id, file_path, start_line, end_line)`. A language-agnostic chunker (`rag_chunker.py`) uses Phase 3a's tree-sitter parser to split Python files at top-level symbol boundaries with a 40-line sliding-window fallback for long symbols and unparseable files. Indexing runs behind an in-memory `IndexJobTracker`: the route spawns an `asyncio.Task`, stores status in a dict, returns `job_id` immediately; concurrent POSTs for the same project get 409. Embedding goes through the existing `OllamaClient.embed` (Phase 2).

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, sqlite3 + `sqlite-vec>=0.1.9`, `tree-sitter-python` (reused from Phase 3a), `httpx` (reused), pytest.

**Parent spec:** [`docs/superpowers/specs/2026-04-19-balu-code-phase-3b-rag-design.md`](../specs/2026-04-19-balu-code-phase-3b-rag-design.md)

---

## File Structure (this phase)

```
Balu_Code/
└── plugin/
    ├── plugin.json                                    ← modified (Task 2)
    ├── requirements.txt                               ← modified (Task 2)
    ├── pyproject.toml                                 ← modified (Task 2)
    ├── __init__.py                                    ← modified (Task 9)
    ├── deps.py                                        ← modified (Task 9)
    ├── schemas.py                                     ← modified (Task 8)
    ├── routes.py                                      ← modified (Tasks 10, 11)
    ├── services/
    │   ├── repo_map.py                                ← modified (Task 1: public IGNORE_DIRS)
    │   ├── repo_map_python.py                         ← modified (Task 1: public get_parser)
    │   ├── rag_chunker.py                             ← new (Task 3)
    │   ├── rag_index.py                               ← new (Tasks 4, 5)
    │   ├── rag_registry.py                            ← new (Task 6)
    │   ├── index_jobs.py                              ← new (Task 7)
    │   └── indexer.py                                 ← new (Task 8)
    └── tests/
        ├── test_rag_chunker.py                        ← new (Task 3)
        ├── test_rag_index.py                          ← new (Tasks 4, 5)
        ├── test_rag_registry.py                       ← new (Task 6)
        ├── test_index_jobs.py                         ← new (Task 7)
        ├── test_indexer.py                            ← new (Task 8)
        ├── test_plugin_lifecycle.py                   ← extended (Task 9)
        └── test_routes_index.py                       ← new (Tasks 10, 11)
```

Task 12 is end-of-phase verification.

---

## Task 1: Promote `IGNORE_DIRS` and `get_parser` to public

**Files:**
- Modify: `plugin/services/repo_map.py`
- Modify: `plugin/services/repo_map_python.py`

Phase 3b's indexer and chunker need to reuse the ignore-list and the tree-sitter parser singleton. Today they are module-private (`_IGNORE_DIRS`, `_get_parser`). Promote them to public in a behaviour-neutral rename.

- [ ] **Step 1: Rename `_IGNORE_DIRS` → `IGNORE_DIRS` in `plugin/services/repo_map.py`**

Find the current constant block near the top of the file:

```python
_IGNORE_DIRS = frozenset(
    {
        "__pycache__",
        ".venv",
        ...
    }
)
```

Rename to `IGNORE_DIRS` (drop the underscore). Update any internal references in the same file (there's one in `_is_ignored`).

Update the module's `__all__` block at the bottom to include `IGNORE_DIRS` (alphabetical):

```python
__all__ = [
    "IGNORE_DIRS",
    "ProjectRootNotAccessible",
    "RepoMap",
    "RepoMapError",
]
```

- [ ] **Step 2: Rename `_get_parser` → `get_parser` in `plugin/services/repo_map_python.py`**

Find `def _get_parser() -> Parser:` (near the top, below the imports). Rename to `get_parser`. Update all internal callers in the same file (one call inside `parse_python_file`).

Add to the module's `__all__` (alphabetical):

```python
__all__ = ["get_parser", "parse_python_file"]
```

- [ ] **Step 3: Run the full suite to verify no behaviour change**

```bash
source .venv/bin/activate
ruff check .
pytest
```

Expected:
- ruff: clean.
- pytest: **141 passed** (unchanged).

- [ ] **Step 4: Commit**

```bash
git add plugin/services/repo_map.py plugin/services/repo_map_python.py
git commit -m "refactor(plugin): promote IGNORE_DIRS and get_parser to public API"
```

---

## Task 2: Add `sqlite-vec` dependency

**Files:**
- Modify: `plugin/plugin.json`
- Modify: `plugin/requirements.txt`
- Modify: `plugin/pyproject.toml`

- [ ] **Step 1: Update `plugin/plugin.json`** — extend `python_requirements`:

Current:

```json
  "python_requirements": [
    "httpx>=0.27",
    "pydantic>=2.6",
    "tree-sitter>=0.22",
    "tree-sitter-python>=0.21"
  ],
```

Replace with:

```json
  "python_requirements": [
    "httpx>=0.27",
    "pydantic>=2.6",
    "sqlite-vec>=0.1.9",
    "tree-sitter>=0.22",
    "tree-sitter-python>=0.21"
  ],
```

- [ ] **Step 2: Update `plugin/requirements.txt`** — append `sqlite-vec>=0.1.9` so the full file becomes:

```
httpx>=0.27
pydantic>=2.6
sqlite-vec>=0.1.9
tree-sitter>=0.22
tree-sitter-python>=0.21
```

- [ ] **Step 3: Update `plugin/pyproject.toml`** — extend `[project] dependencies`:

Find:

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

Insert `sqlite-vec>=0.1.9` alphabetically:

```toml
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.6",
  "sqlite-vec>=0.1.9",
  "tree-sitter>=0.22",
  "tree-sitter-python>=0.21",
  "fastapi>=0.110",
  "balu-code-shared",
]
```

- [ ] **Step 4: Install**

```bash
source .venv/bin/activate
pip install -e "plugin[dev]"
```

Expected: `sqlite-vec` installs cleanly. On Linux x86_64 a prebuilt wheel exists; no C toolchain required.

- [ ] **Step 5: Smoke-test**

```bash
python -c "
import sqlite3
import sqlite_vec
conn = sqlite3.connect(':memory:')
conn.enable_load_extension(True)
sqlite_vec.load(conn)
conn.enable_load_extension(False)
row = conn.execute('SELECT vec_version()').fetchone()
print('ok', row[0])
"
```

Expected: `ok v0.1.9` (or similar version string).

- [ ] **Step 6: Run the existing suite — no regression**

```bash
ruff check .
pytest
```

Expected: 141 passed, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add plugin/plugin.json plugin/requirements.txt plugin/pyproject.toml
git commit -m "build(plugin): add sqlite-vec dependency"
```

---

## Task 3: `rag_chunker.py` — chunk_python_file + tests

**Files:**
- Create: `plugin/services/rag_chunker.py`
- Create: `plugin/tests/test_rag_chunker.py`

TDD. The chunker is a pure function; no DB, no network.

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_rag_chunker.py`:

```python
"""Tests for chunk_python_file."""
from __future__ import annotations

from plugin.services.rag_chunker import Chunk, chunk_python_file


def test_empty_source_returns_empty_list():
    assert chunk_python_file("a.py", b"") == []


def test_single_short_function_one_chunk():
    src = b"def foo(x):\n    return x\n"
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.file_path == "a.py"
    assert c.start_line == 1
    assert c.end_line == 2
    assert c.text == "def foo(x):\n    return x\n"


def test_prologue_emitted_before_first_symbol():
    src = (
        b"\"\"\"Module docstring.\"\"\"\n"
        b"import os\n"
        b"\n"
        b"def foo():\n"
        b"    return 1\n"
    )
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 2
    prologue, func = chunks
    assert prologue.start_line == 1
    assert prologue.end_line == 3
    assert "Module docstring" in prologue.text
    assert "import os" in prologue.text
    assert func.start_line == 4
    assert func.end_line == 5
    assert func.text.startswith("def foo")


def test_two_adjacent_symbols_no_gap_chunk():
    src = (
        b"def foo():\n    return 1\n"
        b"def bar():\n    return 2\n"
    )
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 2
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 2
    assert chunks[1].start_line == 3
    assert chunks[1].end_line == 4


def test_gap_between_symbols_emitted_as_separate_chunk():
    src = (
        b"def foo():\n    return 1\n"
        b"\n"
        b"# A comment spanning\n"
        b"# multiple lines.\n"
        b"\n"
        b"def bar():\n    return 2\n"
    )
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 3
    foo, gap, bar = chunks
    assert foo.text.startswith("def foo")
    assert gap.text.strip().startswith("# A comment")
    assert bar.text.startswith("def bar")


def test_tail_after_last_symbol_emitted():
    src = (
        b"def foo():\n    return 1\n"
        b"\n"
        b"TRAILING = 42\n"
    )
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 2
    assert chunks[0].text.startswith("def foo")
    assert "TRAILING = 42" in chunks[1].text


def test_long_symbol_split_into_sliding_windows():
    # One function that is 100 lines long. Default symbol_max_lines=80.
    body_lines = [f"    x_{i} = {i}\n" for i in range(98)]
    src = b"def big():\n" + b"".join(line.encode() for line in body_lines) + b"    return None\n"
    chunks = chunk_python_file("a.py", src, window_lines=40, overlap_lines=10)
    assert len(chunks) >= 2
    # All chunks stay inside the function's line range [1, 100].
    for c in chunks:
        assert c.start_line >= 1
        assert c.end_line <= 100
    # Windows overlap: second chunk's start_line < first chunk's end_line.
    assert chunks[1].start_line < chunks[0].end_line


def test_no_symbols_fallback_to_sliding_windows():
    # 50 lines of module-level code, no defs/classes.
    src = b"\n".join(f"CONST_{i} = {i}".encode() for i in range(50)) + b"\n"
    chunks = chunk_python_file("a.py", src, window_lines=40, overlap_lines=10)
    assert len(chunks) == 2  # windows at [1,40] and [31,50]
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 40
    assert chunks[1].start_line == 31
    assert chunks[1].end_line == 50


def test_decorated_function_included_in_chunk_range():
    src = (
        b"@staticmethod\n"
        b"def foo():\n"
        b"    return 1\n"
    )
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.start_line == 1  # decorator line included
    assert c.end_line == 3
    assert "@staticmethod" in c.text


def test_class_with_methods_is_one_chunk():
    src = (
        b"class Service:\n"
        b"    def a(self):\n        return 1\n"
        b"    def b(self):\n        return 2\n"
    )
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 1
    assert chunks[0].text.startswith("class Service:")
    assert "def a" in chunks[0].text
    assert "def b" in chunks[0].text


def test_syntax_error_fallback_to_sliding_windows():
    # Unparseable but non-empty; fallback must still produce at least one chunk.
    src = b"def broken(\n" + b"x = 1\n" * 50
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) >= 1
    # All chunks cover the file exactly (no crashes).
    for c in chunks:
        assert 1 <= c.start_line <= c.end_line


def test_chunk_text_decodes_non_utf8_safely():
    # Invalid UTF-8 bytes must not raise; errors='replace' turns them into U+FFFD.
    src = b"def foo():\n    return '\xff\xfe'\n"
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 1
    assert "foo" in chunks[0].text


def test_returns_Chunk_dataclass_instances():
    src = b"def f(): pass\n"
    chunks = chunk_python_file("a.py", src)
    assert isinstance(chunks[0], Chunk)
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
pytest plugin/tests/test_rag_chunker.py -v
```

Expected: `ModuleNotFoundError: No module named 'plugin.services.rag_chunker'`.

- [ ] **Step 3: Implement `plugin/services/rag_chunker.py`**

```python
"""Pure-function chunker for RAG embedding.

Splits a Python source file into chunks at tree-sitter top-level symbol
boundaries (``class_definition`` / ``function_definition`` / wrapping
``decorated_definition``), with a sliding-window fallback for long
symbols and unparseable files. Decorators are included in the symbol's
line range so the chunk captures the full "definition unit".

This module is stateless and synchronous. It is called from the
indexer worker (``plugin.services.indexer``), which handles embedding
and persistence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from plugin.services.repo_map_python import get_parser


@dataclass(frozen=True)
class Chunk:
    file_path: str
    start_line: int   # 1-indexed, inclusive
    end_line: int     # 1-indexed, inclusive
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

    - Top-level ``class`` / ``def`` (and ``decorated_definition`` wrapping
      one) become one chunk each, unless their line span exceeds
      ``symbol_max_lines``, in which case they are split into sliding
      windows of ``window_lines`` with ``overlap_lines`` overlap.
    - Lines between symbols (module docstring + imports before the first
      symbol, inter-symbol gaps, trailing module-level code) become
      single non-symbol chunks. For v1 these are emitted whole, not
      split — they are usually short (imports / a comment block).
    - If the parser returns zero top-level symbols (empty file, pure
      module-level code, syntax error), the whole file is split into
      sliding windows.
    - Empty ``source`` returns an empty list.
    """
    if not source:
        return []

    text = source.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    n_lines = len(lines)
    if n_lines == 0:
        return []

    ranges = _extract_top_level_ranges(source)

    if not ranges:
        return list(_sliding_windows(file_path, lines, 1, n_lines, window_lines, overlap_lines))

    chunks: list[Chunk] = []
    cursor = 1

    for start, end in ranges:
        if cursor <= start - 1:
            chunks.append(_build_chunk(file_path, lines, cursor, start - 1))

        span = end - start + 1
        if span <= symbol_max_lines:
            chunks.append(_build_chunk(file_path, lines, start, end))
        else:
            chunks.extend(_sliding_windows(file_path, lines, start, end, window_lines, overlap_lines))

        cursor = end + 1

    if cursor <= n_lines:
        chunks.append(_build_chunk(file_path, lines, cursor, n_lines))

    return chunks


def _extract_top_level_ranges(source: bytes) -> list[tuple[int, int]]:
    """Return (start_line, end_line) pairs for top-level symbols, 1-indexed inclusive, sorted ascending.

    Recognised node types: ``class_definition``, ``function_definition``,
    and ``decorated_definition`` wrapping either. For a decorated
    definition, the range covers the decorator line(s) too.
    """
    parser = get_parser()
    try:
        tree = parser.parse(source)
    except Exception:
        return []

    ranges: list[tuple[int, int]] = []
    for node in tree.root_node.children:
        nt = node.type
        if nt in ("class_definition", "function_definition"):
            ranges.append((node.start_point[0] + 1, node.end_point[0] + 1))
        elif nt == "decorated_definition":
            inner = node.child_by_field_name("definition")
            if inner is not None and inner.type in ("class_definition", "function_definition"):
                ranges.append((node.start_point[0] + 1, node.end_point[0] + 1))
    ranges.sort()
    return ranges


def _build_chunk(file_path: str, lines: list[str], start: int, end: int) -> Chunk:
    return Chunk(
        file_path=file_path,
        start_line=start,
        end_line=end,
        text="".join(lines[start - 1:end]),
    )


def _sliding_windows(
    file_path: str,
    lines: list[str],
    start: int,
    end: int,
    window_lines: int,
    overlap_lines: int,
) -> Iterable[Chunk]:
    stride = max(1, window_lines - overlap_lines)
    pos = start
    while pos <= end:
        win_end = min(pos + window_lines - 1, end)
        yield _build_chunk(file_path, lines, pos, win_end)
        if win_end == end:
            break
        pos += stride


__all__ = ["Chunk", "chunk_python_file"]
```

- [ ] **Step 4: Run the chunker tests**

```bash
pytest plugin/tests/test_rag_chunker.py -v
```

Expected: **13 passed**.

- [ ] **Step 5: Run the full suite + ruff**

```bash
ruff check .
ruff format --check .
pytest
```

Expected: 154 passed (141 + 13).

- [ ] **Step 6: Commit**

```bash
git add plugin/services/rag_chunker.py plugin/tests/test_rag_chunker.py
git commit -m "feat(plugin): add rag_chunker with symbol-boundary chunks and sliding-window fallback"
```

---

## Task 4: `rag_index.py` — storage surface

**Files:**
- Create: `plugin/services/rag_index.py` (first cut: errors, dataclasses, open/close/upsert/delete/get_file_sha1/all_indexed_paths — no search yet)
- Create: `plugin/tests/test_rag_index.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_rag_index.py`:

```python
"""Tests for RagIndex storage and open/close lifecycle."""
from __future__ import annotations

import pytest

from plugin.services.rag_chunker import Chunk
from plugin.services.rag_index import (
    RagIndex,
    RagIndexUnavailable,
)


class _FakeOllama:
    """Deterministic 768-dim bag-of-words embedder for tests."""

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        vecs: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for token in _tokens(text):
                bucket = hash(token) % self.dim
                vec[bucket] = 1.0
            vecs.append(vec)
        return vecs

    async def close(self) -> None:
        pass


def _tokens(text: str) -> list[str]:
    import re

    return [t for t in re.split(r"\W+", text.lower()) if len(t) >= 3]


@pytest.fixture
async def index(tmp_path):
    ollama = _FakeOllama()
    idx = RagIndex(
        db_path=tmp_path / "rag.db",
        embed_model="nomic-embed-text",
        ollama=ollama,
    )
    await idx.open()
    yield idx
    await idx.close()


async def test_open_creates_schema_idempotently(tmp_path):
    ollama = _FakeOllama()
    idx = RagIndex(tmp_path / "rag.db", "nomic-embed-text", ollama)
    await idx.open()
    await idx.close()
    # Second open on the same file must not raise.
    idx2 = RagIndex(tmp_path / "rag.db", "nomic-embed-text", ollama)
    await idx2.open()
    assert await idx2.all_indexed_paths() == set()
    await idx2.close()


async def test_upsert_inserts_chunks_and_embedding_rows(index):
    chunks = [
        Chunk(file_path="a.py", start_line=1, end_line=5, text="def foo(): pass"),
        Chunk(file_path="a.py", start_line=6, end_line=10, text="class Bar: pass"),
    ]
    await index.upsert_file_chunks("a.py", "sha1_abc", chunks)
    assert await index.all_indexed_paths() == {"a.py"}
    assert await index.get_file_sha1("a.py") == "sha1_abc"


async def test_upsert_replaces_existing_chunks_for_same_path(index):
    c_old = Chunk(file_path="a.py", start_line=1, end_line=5, text="old body")
    await index.upsert_file_chunks("a.py", "sha1_old", [c_old])
    c_new = Chunk(file_path="a.py", start_line=1, end_line=3, text="new body")
    await index.upsert_file_chunks("a.py", "sha1_new", [c_new])
    assert await index.get_file_sha1("a.py") == "sha1_new"
    # Should be exactly one chunk in storage now (the replacement).
    paths = await index.all_indexed_paths()
    assert paths == {"a.py"}


async def test_upsert_empty_chunk_list_is_a_noop(index):
    # Calling upsert_file_chunks with an empty list should not create rows.
    await index.upsert_file_chunks("nothing.py", "sha1", [])
    assert "nothing.py" not in await index.all_indexed_paths()


async def test_delete_file_chunks_removes_both_tables(index):
    c = Chunk(file_path="a.py", start_line=1, end_line=5, text="x")
    await index.upsert_file_chunks("a.py", "sha1", [c])
    await index.delete_file_chunks("a.py")
    assert await index.all_indexed_paths() == set()
    assert await index.get_file_sha1("a.py") is None


async def test_get_file_sha1_returns_none_for_unknown(index):
    assert await index.get_file_sha1("missing.py") is None


async def test_multiple_files_isolated(index):
    await index.upsert_file_chunks(
        "a.py",
        "sha_a",
        [Chunk(file_path="a.py", start_line=1, end_line=1, text="A")],
    )
    await index.upsert_file_chunks(
        "b.py",
        "sha_b",
        [Chunk(file_path="b.py", start_line=1, end_line=1, text="B")],
    )
    assert await index.all_indexed_paths() == {"a.py", "b.py"}
    await index.delete_file_chunks("a.py")
    assert await index.all_indexed_paths() == {"b.py"}
    assert await index.get_file_sha1("b.py") == "sha_b"


async def test_unavailable_when_sqlite_vec_cannot_load(tmp_path, monkeypatch):
    def _boom(conn):
        raise RuntimeError("loader exploded")

    monkeypatch.setattr("plugin.services.rag_index.sqlite_vec.load", _boom)
    ollama = _FakeOllama()
    idx = RagIndex(tmp_path / "rag.db", "nomic-embed-text", ollama)
    with pytest.raises(RagIndexUnavailable):
        await idx.open()
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
pytest plugin/tests/test_rag_index.py -v
```

Expected: `ModuleNotFoundError: No module named 'plugin.services.rag_index'`.

- [ ] **Step 3: Implement `plugin/services/rag_index.py`** (storage half only — search arrives in Task 5)

```python
"""Per-project sqlite-vec index for chunk embeddings.

One RagIndex instance per project; the registry (``rag_registry.py``)
owns the map. The DB file is self-contained: ``project_id`` lives in
the filename, not in the rows, so an index is dropped by deleting one
file.

All operations are blocking sqlite3 calls wrapped in ``asyncio.to_thread``
by the caller. Methods exposed on this class are already ``async``,
but the thread-dispatch happens at the call site to match how the rest
of the plugin handles blocking I/O (see routes.py).

Wait — actually the async boundary here is simpler: we wrap the sync
work inside each method with ``asyncio.to_thread``. That keeps the
public API async-friendly without forcing every caller to remember the
to_thread dance for individual DB operations.
"""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec

from plugin.services.ollama_client import OllamaClient
from plugin.services.rag_chunker import Chunk


class RagIndexError(Exception):
    """Base class for RAG-index errors."""


class RagIndexUnavailable(RagIndexError):
    """Raised when the sqlite-vec extension cannot be loaded."""


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float  # cosine similarity (higher is better), with optional keyword boost


_SCHEMA = """
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
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RagIndex:
    def __init__(
        self,
        db_path: Path,
        embed_model: str,
        ollama: OllamaClient,
        vector_dim: int = 768,
    ) -> None:
        self._db_path = db_path
        self._embed_model = embed_model
        self._ollama = ollama
        self._vector_dim = vector_dim
        self._conn: sqlite3.Connection | None = None

    async def open(self) -> None:
        await asyncio.to_thread(self._open_sync)

    def _open_sync(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        except Exception as exc:
            conn.close()
            raise RagIndexUnavailable(f"sqlite-vec failed to load: {exc}") from exc
        conn.enable_load_extension(False)
        conn.executescript(_SCHEMA)
        # vec0 virtual table: create separately because vec0 doesn't like being
        # inside an executescript that also has other CREATE TABLE statements.
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
            f"embedding float[{self._vector_dim}])"
        )
        conn.commit()
        self._conn = conn

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def upsert_file_chunks(
        self, file_path: str, file_sha1: str, chunks: list[Chunk]
    ) -> None:
        if not chunks:
            return
        embeddings = await self._ollama.embed(self._embed_model, [c.text for c in chunks])
        await asyncio.to_thread(
            self._upsert_sync, file_path, file_sha1, chunks, embeddings
        )

    def _upsert_sync(
        self,
        file_path: str,
        file_sha1: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        assert self._conn is not None, "RagIndex not opened"
        conn = self._conn
        now = _now_iso()
        with conn:  # implicit transaction
            # Remove any existing rows for this file_path first.
            old_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM chunks WHERE file_path = ?", (file_path,)
                ).fetchall()
            ]
            if old_ids:
                placeholders = ",".join("?" * len(old_ids))
                conn.execute(
                    f"DELETE FROM chunks WHERE id IN ({placeholders})",  # noqa: S608
                    old_ids,
                )
                conn.execute(
                    f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})",  # noqa: S608
                    old_ids,
                )
            for chunk, vec in zip(chunks, embeddings, strict=True):
                cur = conn.execute(
                    "INSERT INTO chunks "
                    "(file_path, start_line, end_line, text, file_sha1, embedded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        chunk.file_path,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.text,
                        file_sha1,
                        now,
                    ),
                )
                new_id = cur.lastrowid
                conn.execute(
                    "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
                    (new_id, sqlite_vec.serialize_float32(vec)),
                )

    async def delete_file_chunks(self, file_path: str) -> None:
        await asyncio.to_thread(self._delete_sync, file_path)

    def _delete_sync(self, file_path: str) -> None:
        assert self._conn is not None
        conn = self._conn
        with conn:
            ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM chunks WHERE file_path = ?", (file_path,)
                ).fetchall()
            ]
            if not ids:
                return
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"DELETE FROM chunks WHERE id IN ({placeholders})",  # noqa: S608
                ids,
            )
            conn.execute(
                f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})",  # noqa: S608
                ids,
            )

    async def get_file_sha1(self, file_path: str) -> str | None:
        return await asyncio.to_thread(self._get_file_sha1_sync, file_path)

    def _get_file_sha1_sync(self, file_path: str) -> str | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT file_sha1 FROM chunks WHERE file_path = ? LIMIT 1", (file_path,)
        ).fetchone()
        return row[0] if row is not None else None

    async def all_indexed_paths(self) -> set[str]:
        return await asyncio.to_thread(self._all_paths_sync)

    def _all_paths_sync(self) -> set[str]:
        assert self._conn is not None
        return {row[0] for row in self._conn.execute("SELECT DISTINCT file_path FROM chunks")}


__all__ = [
    "RagIndex",
    "RagIndexError",
    "RagIndexUnavailable",
    "SearchHit",
]
```

- [ ] **Step 4: Run the rag_index tests**

```bash
pytest plugin/tests/test_rag_index.py -v
```

Expected: **8 passed**.

- [ ] **Step 5: Run the full suite + ruff**

```bash
ruff check .
ruff format --check .
pytest
```

Expected: **162 passed** (154 + 8).

- [ ] **Step 6: Commit**

```bash
git add plugin/services/rag_index.py plugin/tests/test_rag_index.py
git commit -m "feat(plugin): add RagIndex storage (sqlite-vec schema + upsert/delete/query helpers)"
```

---

## Task 5: `RagIndex.search` — cosine retrieval + keyword boost

**Files:**
- Modify: `plugin/services/rag_index.py`
- Modify: `plugin/tests/test_rag_index.py`

- [ ] **Step 1: Append failing tests to `plugin/tests/test_rag_index.py`**

Add these test functions at the end of the file:

```python
async def test_search_returns_empty_for_empty_index(index):
    hits = await index.search("anything", top_k=8)
    assert hits == []


async def test_search_orders_by_similarity(index):
    # Two chunks: one mentions "authentication", one mentions "rendering".
    await index.upsert_file_chunks(
        "auth.py",
        "sha_auth",
        [Chunk(file_path="auth.py", start_line=1, end_line=5, text="authentication middleware")],
    )
    await index.upsert_file_chunks(
        "render.py",
        "sha_render",
        [Chunk(file_path="render.py", start_line=1, end_line=5, text="html rendering helpers")],
    )
    hits = await index.search("authentication flow", top_k=2)
    assert len(hits) == 2
    # The auth chunk (more token overlap) must rank first.
    assert hits[0].chunk.file_path == "auth.py"


async def test_search_keyword_boost_shifts_ranking(index):
    # Two chunks with identical "generic" text so their cosine similarity
    # is identical; one has the query token in its file_path, which
    # should win via the +0.15 keyword bonus.
    generic_text = "shared utility helper implementation"
    await index.upsert_file_chunks(
        "widgets.py",
        "sha_w",
        [Chunk(file_path="widgets.py", start_line=1, end_line=5, text=generic_text)],
    )
    await index.upsert_file_chunks(
        "authentication/helpers.py",
        "sha_a",
        [Chunk(
            file_path="authentication/helpers.py",
            start_line=1,
            end_line=5,
            text=generic_text,
        )],
    )
    hits = await index.search("authentication", top_k=2)
    assert hits[0].chunk.file_path == "authentication/helpers.py"


async def test_search_top_k_limits_results(index):
    for i in range(5):
        await index.upsert_file_chunks(
            f"f{i}.py",
            f"sha_{i}",
            [Chunk(file_path=f"f{i}.py", start_line=1, end_line=1, text=f"content {i}")],
        )
    hits = await index.search("content", top_k=3)
    assert len(hits) == 3


async def test_search_score_has_keyword_bonus_applied(index):
    await index.upsert_file_chunks(
        "target.py",
        "sha_t",
        [Chunk(file_path="target.py", start_line=1, end_line=1, text="target content here")],
    )
    hits = await index.search("target", top_k=1)
    assert len(hits) == 1
    # Score = (1 - distance) + 0.15 keyword boost → must exceed 0.15 at minimum.
    assert hits[0].score > 0.15
```

- [ ] **Step 2: Run the new tests and verify they fail**

```bash
pytest plugin/tests/test_rag_index.py -v -k "search"
```

Expected: 5 failures with `AttributeError: 'RagIndex' object has no attribute 'search'`.

- [ ] **Step 3: Add the `search` method to `RagIndex`**

Append this method to the `RagIndex` class in `plugin/services/rag_index.py` (after `all_indexed_paths`):

```python
    async def search(
        self,
        query: str,
        top_k: int = 8,
        *,
        keyword_boost: float = 0.15,
    ) -> list[SearchHit]:
        """Top-K nearest chunks for ``query`` with optional keyword boost.

        1. Embed ``query`` via OllamaClient.
        2. Fetch top ``top_k * 2`` hits from sqlite-vec by cosine distance.
        3. For each hit: ``base_score = 1 - distance``. If any query token
           (case-insensitive, >=3 chars, split on non-alphanumerics) appears
           in ``file_path`` or ``chunk.text`` → ``score = base_score + keyword_boost``.
        4. Sort by score descending, return top ``top_k``.
        """
        if top_k <= 0:
            return []
        query_vecs = await self._ollama.embed(self._embed_model, [query])
        query_vec = query_vecs[0]
        fetch_k = top_k * 2
        rows = await asyncio.to_thread(self._search_sync, query_vec, fetch_k)
        if not rows:
            return []
        tokens = _keyword_tokens(query)
        hits: list[SearchHit] = []
        for file_path, start_line, end_line, text, distance in rows:
            base_score = 1.0 - float(distance)
            boost = keyword_boost if _has_token(tokens, file_path, text) else 0.0
            chunk = Chunk(
                file_path=file_path,
                start_line=int(start_line),
                end_line=int(end_line),
                text=text,
            )
            hits.append(SearchHit(chunk=chunk, score=base_score + boost))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def _search_sync(self, query_vec: list[float], k: int) -> list[tuple]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT chunks.file_path, chunks.start_line, chunks.end_line, "
            "       chunks.text, vec_chunks.distance "
            "FROM vec_chunks "
            "JOIN chunks ON chunks.id = vec_chunks.rowid "
            "WHERE vec_chunks.embedding MATCH ? AND k = ? "
            "ORDER BY vec_chunks.distance",
            (sqlite_vec.serialize_float32(query_vec), k),
        ).fetchall()
        return [tuple(r) for r in rows]
```

Also add the two module-level helpers at the top of the file (after the imports but before `_SCHEMA`):

```python
import re

_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


def _keyword_tokens(query: str) -> set[str]:
    """Lowercased tokens of length >=3 extracted from ``query``."""
    return {t.lower() for t in _TOKEN_RE.findall(query) if len(t) >= 3}


def _has_token(tokens: set[str], file_path: str, text: str) -> bool:
    hay = (file_path + "\n" + text).lower()
    return any(t in hay for t in tokens)
```

Note: `import re` moves to the top-level imports.

- [ ] **Step 4: Run the search tests**

```bash
pytest plugin/tests/test_rag_index.py -v
```

Expected: **13 passed** (8 storage + 5 search).

- [ ] **Step 5: Run the full suite + ruff**

```bash
ruff check .
ruff format --check .
pytest
```

Expected: **167 passed** (162 + 5).

- [ ] **Step 6: Commit**

```bash
git add plugin/services/rag_index.py plugin/tests/test_rag_index.py
git commit -m "feat(plugin): add RagIndex.search with cosine + keyword boost"
```

---

## Task 6: `rag_registry.py` — lazy per-project RagIndex map

**Files:**
- Create: `plugin/services/rag_registry.py`
- Create: `plugin/tests/test_rag_registry.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_rag_registry.py`:

```python
"""Tests for RagRegistry."""
from __future__ import annotations

import pytest

from plugin.services.rag_registry import RagRegistry


class _FakeOllama:
    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 768 for _ in texts]

    async def close(self) -> None:
        pass


@pytest.fixture
def registry(tmp_path) -> RagRegistry:
    return RagRegistry(
        data_dir=tmp_path,
        embed_model="nomic-embed-text",
        ollama=_FakeOllama(),
    )


async def test_get_opens_index_on_first_call(registry, tmp_path):
    idx = await registry.get(1)
    assert idx is not None
    assert (tmp_path / "indices" / "project_1.db").exists()


async def test_get_returns_same_instance_for_same_project(registry):
    a = await registry.get(1)
    b = await registry.get(1)
    assert a is b


async def test_get_returns_distinct_instance_per_project(registry):
    idx1 = await registry.get(1)
    idx2 = await registry.get(2)
    assert idx1 is not idx2


async def test_close_all_closes_every_open_index(registry):
    await registry.get(1)
    await registry.get(2)
    await registry.close_all()
    # After close_all, subsequent get re-opens (and doesn't raise).
    idx = await registry.get(1)
    assert idx is not None
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
pytest plugin/tests/test_rag_registry.py -v
```

Expected: `ModuleNotFoundError: No module named 'plugin.services.rag_registry'`.

- [ ] **Step 3: Implement `plugin/services/rag_registry.py`**

```python
"""Per-plugin registry of RagIndex instances, one per project.

Indices are opened lazily on first access and cached. On plugin
shutdown the registry closes every opened index.

Concurrency: ``get`` is guarded by an ``asyncio.Lock`` so two
simultaneous requests for the same project cannot double-open the DB.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from plugin.services.ollama_client import OllamaClient
from plugin.services.rag_index import RagIndex


class RagRegistry:
    def __init__(
        self,
        data_dir: Path,
        embed_model: str,
        ollama: OllamaClient,
    ) -> None:
        self._data_dir = data_dir
        self._embed_model = embed_model
        self._ollama = ollama
        self._indices: dict[int, RagIndex] = {}
        self._lock = asyncio.Lock()

    async def get(self, project_id: int) -> RagIndex:
        async with self._lock:
            idx = self._indices.get(project_id)
            if idx is not None:
                return idx
            db_path = self._data_dir / "indices" / f"project_{project_id}.db"
            new_idx = RagIndex(
                db_path=db_path,
                embed_model=self._embed_model,
                ollama=self._ollama,
            )
            await new_idx.open()
            self._indices[project_id] = new_idx
            return new_idx

    async def close_all(self) -> None:
        async with self._lock:
            for idx in self._indices.values():
                await idx.close()
            self._indices.clear()


__all__ = ["RagRegistry"]
```

- [ ] **Step 4: Run the registry tests**

```bash
pytest plugin/tests/test_rag_registry.py -v
```

Expected: **4 passed**.

- [ ] **Step 5: Run the full suite + ruff**

```bash
ruff check .
pytest
```

Expected: **171 passed** (167 + 4).

- [ ] **Step 6: Commit**

```bash
git add plugin/services/rag_registry.py plugin/tests/test_rag_registry.py
git commit -m "feat(plugin): add RagRegistry (lazy per-project RagIndex map)"
```

---

## Task 7: `index_jobs.py` — in-memory job tracker

**Files:**
- Create: `plugin/services/index_jobs.py`
- Create: `plugin/tests/test_index_jobs.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_index_jobs.py`:

```python
"""Tests for IndexJobTracker."""
from __future__ import annotations

import asyncio

import pytest

from plugin.services.index_jobs import (
    AlreadyIndexingError,
    IndexJob,
    IndexJobTracker,
    JobStatus,
)


@pytest.fixture
def tracker() -> IndexJobTracker:
    return IndexJobTracker()


async def _wait_for_status(tracker: IndexJobTracker, job_id: str, target: JobStatus, timeout: float = 2.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        j = tracker.get_job(job_id)
        if j is not None and j.status == target:
            return j
        await asyncio.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not reach {target} within {timeout}s")


async def test_start_job_returns_queued_job(tracker):
    async def worker(job: IndexJob) -> None:
        job.status = JobStatus.DONE

    job = tracker.start_job(project_id=1, worker=worker)
    assert isinstance(job, IndexJob)
    assert job.project_id == 1
    assert job.status in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.DONE)
    assert job.id  # non-empty


async def test_worker_runs_and_status_becomes_done(tracker):
    async def worker(job: IndexJob) -> None:
        job.status = JobStatus.RUNNING
        await asyncio.sleep(0)
        job.files_total = 3
        job.files_processed = 3
        job.chunks_total = 7

    job = tracker.start_job(project_id=1, worker=worker)
    final = await _wait_for_status(tracker, job.id, JobStatus.DONE)
    assert final.files_total == 3
    assert final.files_processed == 3
    assert final.chunks_total == 7
    assert final.finished_at is not None


async def test_worker_exception_marks_error(tracker):
    async def worker(job: IndexJob) -> None:
        raise RuntimeError("boom")

    job = tracker.start_job(project_id=1, worker=worker)
    final = await _wait_for_status(tracker, job.id, JobStatus.ERROR)
    assert final.error == "boom"
    assert final.finished_at is not None


async def test_concurrent_start_for_same_project_rejected(tracker):
    gate = asyncio.Event()

    async def slow_worker(job: IndexJob) -> None:
        job.status = JobStatus.RUNNING
        await gate.wait()
        job.status = JobStatus.DONE

    tracker.start_job(project_id=1, worker=slow_worker)
    with pytest.raises(AlreadyIndexingError):
        tracker.start_job(project_id=1, worker=slow_worker)
    # Let the first job finish so the fixture tears down cleanly.
    gate.set()
    await asyncio.sleep(0.05)


async def test_different_projects_can_run_concurrently(tracker):
    gate = asyncio.Event()

    async def worker(job: IndexJob) -> None:
        job.status = JobStatus.RUNNING
        await gate.wait()
        job.status = JobStatus.DONE

    j1 = tracker.start_job(project_id=1, worker=worker)
    j2 = tracker.start_job(project_id=2, worker=worker)
    assert j1.id != j2.id
    gate.set()
    await _wait_for_status(tracker, j1.id, JobStatus.DONE)
    await _wait_for_status(tracker, j2.id, JobStatus.DONE)


async def test_get_job_returns_none_for_unknown_id(tracker):
    assert tracker.get_job("nonexistent") is None


async def test_is_running_for_project_false_after_done(tracker):
    async def worker(job: IndexJob) -> None:
        job.status = JobStatus.DONE

    job = tracker.start_job(project_id=1, worker=worker)
    await _wait_for_status(tracker, job.id, JobStatus.DONE)
    assert tracker.is_running_for_project(1) is False
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
pytest plugin/tests/test_index_jobs.py -v
```

Expected: `ModuleNotFoundError: No module named 'plugin.services.index_jobs'`.

- [ ] **Step 3: Implement `plugin/services/index_jobs.py`**

```python
"""In-memory tracker for indexing jobs.

A job is a UUID-tagged ``IndexJob`` with status / progress fields that
the worker coroutine mutates in place. ``start_job`` spawns the worker
as an ``asyncio.Task`` wrapped in a shim that catches exceptions and
finalises the status. One job per project at a time — concurrent starts
raise ``AlreadyIndexingError``.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class AlreadyIndexingError(Exception):
    """Raised when start_job is called for a project that already has a live job."""


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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


_LIVE = {JobStatus.QUEUED, JobStatus.RUNNING}


class IndexJobTracker:
    def __init__(self) -> None:
        self._jobs: dict[str, IndexJob] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def start_job(
        self,
        project_id: int,
        worker: Callable[[IndexJob], Awaitable[None]],
    ) -> IndexJob:
        if self.is_running_for_project(project_id):
            raise AlreadyIndexingError(f"indexing job for project {project_id} is already running")
        job = IndexJob(
            id=uuid.uuid4().hex,
            project_id=project_id,
            status=JobStatus.QUEUED,
            started_at=_now_iso(),
        )
        self._jobs[job.id] = job
        self._tasks[job.id] = asyncio.create_task(self._run(job, worker))
        return job

    async def _run(
        self,
        job: IndexJob,
        worker: Callable[[IndexJob], Awaitable[None]],
    ) -> None:
        try:
            await worker(job)
            if job.status == JobStatus.RUNNING:
                job.status = JobStatus.DONE
            if job.status in _LIVE:
                # Worker left status as QUEUED — interpret as DONE.
                job.status = JobStatus.DONE
        except Exception as exc:
            job.status = JobStatus.ERROR
            job.error = str(exc)
        finally:
            if job.finished_at is None:
                job.finished_at = _now_iso()

    def get_job(self, job_id: str) -> IndexJob | None:
        return self._jobs.get(job_id)

    def is_running_for_project(self, project_id: int) -> bool:
        return any(
            j.project_id == project_id and j.status in _LIVE
            for j in self._jobs.values()
        )


__all__ = [
    "AlreadyIndexingError",
    "IndexJob",
    "IndexJobTracker",
    "JobStatus",
]
```

- [ ] **Step 4: Run the tracker tests**

```bash
pytest plugin/tests/test_index_jobs.py -v
```

Expected: **7 passed**.

- [ ] **Step 5: Run the full suite + ruff**

```bash
ruff check .
pytest
```

Expected: **178 passed** (171 + 7).

- [ ] **Step 6: Commit**

```bash
git add plugin/services/index_jobs.py plugin/tests/test_index_jobs.py
git commit -m "feat(plugin): add IndexJobTracker (in-memory async job lifecycle)"
```

---

## Task 8: `indexer.py` — worker coroutine

**Files:**
- Create: `plugin/services/indexer.py`
- Create: `plugin/tests/test_indexer.py`
- Modify: `plugin/schemas.py` (add `IndexJobResponse` + `IndexStatusResponse`)

This task introduces the actual indexing work that a job runs, plus the two response schemas Task 10/11's routes will return.

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_indexer.py`:

```python
"""Tests for the indexer worker."""
from __future__ import annotations

import pytest

from plugin.services.index_jobs import IndexJob, JobStatus
from plugin.services.indexer import run_index_job
from plugin.services.rag_chunker import Chunk
from plugin.services.rag_index import RagIndex


class _FakeOllama:
    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        vecs: list[list[float]] = []
        for text in texts:
            vec = [0.0] * 768
            for token in text.lower().split():
                vec[hash(token) % 768] = 1.0
            vecs.append(vec)
        return vecs

    async def close(self) -> None:
        pass


@pytest.fixture
async def index(tmp_path):
    from plugin.services.rag_index import RagIndex

    idx = RagIndex(tmp_path / "rag.db", "nomic-embed-text", _FakeOllama())
    await idx.open()
    yield idx
    await idx.close()


def _write(root, rel, content: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


async def test_indexes_single_python_file(tmp_path, index):
    _write(tmp_path, "a.py", "def foo():\n    return 1\n")
    job = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job, project_root=tmp_path, rag=index)
    assert job.status == JobStatus.DONE
    assert job.files_processed == 1
    assert job.chunks_total >= 1
    assert "a.py" in await index.all_indexed_paths()


async def test_skips_unchanged_files_on_second_run(tmp_path, index):
    _write(tmp_path, "a.py", "def foo():\n    return 1\n")
    job1 = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job1, project_root=tmp_path, rag=index)

    # Second run without any file changes: files_processed should be 0
    # (nothing to reindex).
    job2 = IndexJob(id="j2", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job2, project_root=tmp_path, rag=index)
    assert job2.files_processed == 0
    assert job2.status == JobStatus.DONE


async def test_reindexes_changed_file(tmp_path, index):
    _write(tmp_path, "a.py", "def foo():\n    return 1\n")
    job1 = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job1, project_root=tmp_path, rag=index)

    _write(tmp_path, "a.py", "def foo():\n    return 999\n")
    job2 = IndexJob(id="j2", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job2, project_root=tmp_path, rag=index)
    assert job2.files_processed == 1


async def test_drops_chunks_for_deleted_files(tmp_path, index):
    _write(tmp_path, "a.py", "def foo(): pass\n")
    _write(tmp_path, "b.py", "def bar(): pass\n")
    job1 = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job1, project_root=tmp_path, rag=index)
    assert {"a.py", "b.py"} <= await index.all_indexed_paths()

    (tmp_path / "a.py").unlink()
    job2 = IndexJob(id="j2", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job2, project_root=tmp_path, rag=index)
    assert await index.all_indexed_paths() == {"b.py"}


async def test_ignores_non_python_and_ignored_dirs(tmp_path, index):
    _write(tmp_path, "a.py", "def foo(): pass\n")
    _write(tmp_path, "README.md", "docs\n")
    _write(tmp_path, ".venv/ignored.py", "def bad(): pass\n")
    _write(tmp_path, "__pycache__/cached.py", "def cached(): pass\n")
    job = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job, project_root=tmp_path, rag=index)
    assert await index.all_indexed_paths() == {"a.py"}


async def test_empty_project_root_completes_with_zero(tmp_path, index):
    job = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job, project_root=tmp_path, rag=index)
    assert job.files_processed == 0
    assert job.status == JobStatus.DONE
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
pytest plugin/tests/test_indexer.py -v
```

Expected: `ModuleNotFoundError: No module named 'plugin.services.indexer'`.

- [ ] **Step 3: Implement `plugin/services/indexer.py`**

```python
"""Indexing worker coroutine.

Called by ``IndexJobTracker.start_job`` with an ``IndexJob`` that the
worker mutates as it progresses. Walks the project root, compares each
``.py`` file's sha1 against the cached sha1 in ``RagIndex``, chunks +
embeds + upserts changed files, and drops stale cache rows for deleted
files.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from plugin.services.index_jobs import IndexJob, JobStatus
from plugin.services.rag_chunker import chunk_python_file
from plugin.services.rag_index import RagIndex
from plugin.services.repo_map import IGNORE_DIRS


async def run_index_job(
    job: IndexJob,
    *,
    project_root: Path,
    rag: RagIndex,
) -> None:
    """Drive an indexing pass. Mutates ``job`` in place as it progresses."""
    job.status = JobStatus.RUNNING

    seen_paths: set[str] = set()
    files_to_process: list[tuple[str, bytes, str]] = []

    for fs_path, rel_posix in _iter_python_files(project_root):
        seen_paths.add(rel_posix)
        content_bytes = fs_path.read_bytes()
        sha1 = hashlib.sha1(content_bytes).hexdigest()  # noqa: S324
        cached = await rag.get_file_sha1(rel_posix)
        if cached == sha1:
            continue
        files_to_process.append((rel_posix, content_bytes, sha1))

    job.files_total = len(files_to_process)

    for rel_posix, content_bytes, sha1 in files_to_process:
        chunks = chunk_python_file(rel_posix, content_bytes)
        await rag.upsert_file_chunks(rel_posix, sha1, chunks)
        job.files_processed += 1
        job.chunks_total += len(chunks)

    indexed = await rag.all_indexed_paths()
    for stale in indexed - seen_paths:
        await rag.delete_file_chunks(stale)

    job.status = JobStatus.DONE


def _iter_python_files(project_root: Path):
    """Yield (fs_path, rel_posix) for every .py file under project_root, pruning IGNORE_DIRS."""
    for dirpath_str, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        dirpath = Path(dirpath_str)
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fs_path = dirpath / fname
            if not fs_path.is_file():
                continue
            rel_posix = fs_path.relative_to(project_root).as_posix()
            yield fs_path, rel_posix


__all__ = ["run_index_job"]
```

- [ ] **Step 4: Add response schemas to `plugin/schemas.py`**

Append at the end of `plugin/schemas.py` (after `RepoMapResponse`):

```python
from plugin.services.index_jobs import JobStatus  # noqa: E402


class IndexJobResponse(BaseModel):
    job_id: str
    project_id: int
    status: JobStatus


class IndexStatusResponse(BaseModel):
    job_id: str
    project_id: int
    status: JobStatus
    files_total: int
    files_processed: int
    chunks_total: int
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
```

Update `__all__` to include both, alphabetically. After the change `__all__` reads:

```python
__all__ = [
    "IndexJobResponse",
    "IndexStatusResponse",
    "ModelsResponse",
    "ProjectCreate",
    "ProjectsResponse",
    "RepoMapResponse",
]
```

- [ ] **Step 5: Run the indexer tests**

```bash
pytest plugin/tests/test_indexer.py -v
```

Expected: **6 passed**.

- [ ] **Step 6: Run the full suite + ruff**

```bash
ruff check .
ruff format --check .
pytest
```

Expected: **184 passed** (178 + 6).

- [ ] **Step 7: Commit**

```bash
git add plugin/services/indexer.py plugin/tests/test_indexer.py plugin/schemas.py
git commit -m "feat(plugin): add indexer worker + IndexJob/IndexStatus response schemas"
```

---

## Task 9: Plugin lifecycle wiring (`deps.py` + `__init__.py`)

**Files:**
- Modify: `plugin/deps.py`
- Modify: `plugin/__init__.py`
- Modify: `plugin/tests/test_plugin_lifecycle.py`

- [ ] **Step 1: Append failing tests to `plugin/tests/test_plugin_lifecycle.py`**

Append at the end of the file:

```python
async def test_startup_registers_rag_registry_and_tracker(tmp_path, monkeypatch):
    from plugin.deps import (
        clear_singletons,
        get_index_job_tracker,
        get_rag_registry,
    )
    from plugin.services.index_jobs import IndexJobTracker
    from plugin.services.rag_registry import RagRegistry

    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    clear_singletons()
    p = BaluCodePlugin()
    await p.on_startup()
    try:
        registry = get_rag_registry()
        tracker = get_index_job_tracker()
        assert isinstance(registry, RagRegistry)
        assert isinstance(tracker, IndexJobTracker)
    finally:
        await p.on_shutdown()


async def test_shutdown_clears_rag_registry_and_tracker(tmp_path, monkeypatch):
    from plugin.deps import (
        clear_singletons,
        get_index_job_tracker,
        get_rag_registry,
    )

    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    clear_singletons()
    p = BaluCodePlugin()
    await p.on_startup()
    await p.on_shutdown()
    with pytest.raises(RuntimeError):
        get_rag_registry()
    with pytest.raises(RuntimeError):
        get_index_job_tracker()
```

- [ ] **Step 2: Run the new lifecycle tests and verify they fail**

```bash
pytest plugin/tests/test_plugin_lifecycle.py -v -k "rag_registry or job_tracker"
```

Expected: 2 failures (ImportError: cannot import name `get_rag_registry` from `plugin.deps`).

- [ ] **Step 3: Extend `plugin/deps.py`**

Replace the current `plugin/deps.py` body with:

```python
"""Module-level singletons for the balu_code plugin.

``BaluCodePlugin.on_startup`` constructs the ProjectStore, OllamaClient,
RagRegistry, and IndexJobTracker and registers them here via
``set_singletons``. Route handlers depend on the ``get_*`` accessors so
tests can override them with ``app.dependency_overrides``.
"""
from __future__ import annotations

from plugin.services.index_jobs import IndexJobTracker
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore
from plugin.services.rag_registry import RagRegistry

_store: ProjectStore | None = None
_ollama: OllamaClient | None = None
_rag_registry: RagRegistry | None = None
_index_job_tracker: IndexJobTracker | None = None


def set_singletons(
    store: ProjectStore,
    ollama: OllamaClient,
    rag_registry: RagRegistry,
    index_job_tracker: IndexJobTracker,
) -> None:
    global _store, _ollama, _rag_registry, _index_job_tracker
    _store = store
    _ollama = ollama
    _rag_registry = rag_registry
    _index_job_tracker = index_job_tracker


def clear_singletons() -> None:
    global _store, _ollama, _rag_registry, _index_job_tracker
    _store = None
    _ollama = None
    _rag_registry = None
    _index_job_tracker = None


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


__all__ = [
    "clear_singletons",
    "get_index_job_tracker",
    "get_ollama_client",
    "get_project_store",
    "get_rag_registry",
    "set_singletons",
]
```

- [ ] **Step 4: Update `plugin/__init__.py`** to construct the two new singletons and wire them through the lifecycle

Replace the file with:

```python
"""Balu Code BaluHost plugin.

Loaded at BaluHost startup by PluginManager. Exposes a FastAPI router at
/api/plugins/balu_code/ — see ``plugin/routes.py`` for the route surface.
Owns four singletons: a SQLite-backed ProjectStore, an async OllamaClient,
a RagRegistry (per-project sqlite-vec indices), and an IndexJobTracker.
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
from plugin.services.index_jobs import IndexJobTracker
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore
from plugin.services.rag_registry import RagRegistry

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


class BaluCodePlugin(PluginBase):
    """Main plugin class. Metadata read from plugin.json at import time."""

    def __init__(self) -> None:
        self._config = BaluCodePluginConfig()
        self._store: ProjectStore | None = None
        self._ollama: OllamaClient | None = None
        self._rag_registry: RagRegistry | None = None
        self._index_job_tracker: IndexJobTracker | None = None

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
        rag_registry = RagRegistry(
            data_dir=data_dir,
            embed_model=self._config.embed_model,
            ollama=ollama,
        )
        index_job_tracker = IndexJobTracker()
        self._store = store
        self._ollama = ollama
        self._rag_registry = rag_registry
        self._index_job_tracker = index_job_tracker
        set_singletons(store, ollama, rag_registry, index_job_tracker)

    async def on_shutdown(self) -> None:
        if (
            self._store is None
            and self._ollama is None
            and self._rag_registry is None
            and self._index_job_tracker is None
        ):
            return
        if self._rag_registry is not None:
            await self._rag_registry.close_all()
        if self._ollama is not None:
            await self._ollama.close()
        if self._store is not None:
            self._store.close()
        clear_singletons()
        self._store = None
        self._ollama = None
        self._rag_registry = None
        self._index_job_tracker = None


__all__ = ["BaluCodePlugin"]
```

- [ ] **Step 5: Run the lifecycle tests**

```bash
pytest plugin/tests/test_plugin_lifecycle.py -v
```

Expected: **7 passed** (5 original + 2 new).

- [ ] **Step 6: Run the full suite + ruff**

```bash
ruff check .
ruff format --check .
pytest
```

Expected: **186 passed** (184 + 2).

- [ ] **Step 7: Commit**

```bash
git add plugin/deps.py plugin/__init__.py plugin/tests/test_plugin_lifecycle.py
git commit -m "feat(plugin): wire RagRegistry + IndexJobTracker into lifecycle + deps"
```

---

## Task 10: `POST /projects/{id}/index` route

**Files:**
- Modify: `plugin/routes.py`
- Create: `plugin/tests/test_routes_index.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_routes_index.py`:

```python
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
from plugin.services.rag_chunker import Chunk
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
            idx = RagIndex(
                self._tmp / f"rag_{project_id}.db", "nomic-embed-text", _FakeOllama()
            )
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


def _make_project(store: ProjectStore, root: str) -> int:
    p = store.create_project(name="idx-route", root_path=root, config_yaml=None)
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


async def _wait_status(tracker: IndexJobTracker, job_id: str, target: JobStatus, timeout: float = 3.0):
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
    from fastapi import HTTPException, status as _status

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
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
pytest plugin/tests/test_routes_index.py -v
```

Expected: 4 failures (`404` when the route isn't defined — many of the asserts fail with `status_code == 404`).

- [ ] **Step 3: Extend `plugin/routes.py`**

At the top of `plugin/routes.py`, extend the existing schemas import to include the two new response models and add imports for the new services:

```python
from plugin.schemas import (
    IndexJobResponse,
    IndexStatusResponse,
    ModelsResponse,
    ProjectCreate,
    ProjectsResponse,
    RepoMapResponse,
)
```

Add new top-level imports:

```python
from plugin.deps import (
    get_index_job_tracker,
    get_ollama_client,
    get_project_store,
    get_rag_registry,
)
from plugin.services.index_jobs import (
    AlreadyIndexingError,
    IndexJob,
    IndexJobTracker,
    JobStatus,
)
from plugin.services.indexer import run_index_job
from plugin.services.rag_index import RagIndexUnavailable
from plugin.services.rag_registry import RagRegistry
```

(Adjust alphabetical ordering to match the existing style; ruff will fix.)

Inside `build_router`, before the final `return router`, append:

```python
    @router.post(
        "/projects/{project_id}/index",
        response_model=IndexJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["balu_code"],
    )
    async def start_index_job(
        project_id: int,
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
        rag_registry: RagRegistry = Depends(get_rag_registry),
        tracker: IndexJobTracker = Depends(get_index_job_tracker),
    ) -> IndexJobResponse:
        try:
            project = await asyncio.to_thread(store.get_project, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"project {project_id} not found",
            ) from exc

        try:
            rag = await rag_registry.get(project.id)
        except RagIndexUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"rag index unavailable: {exc}",
            ) from exc

        project_root = Path(project.root_path)

        async def _worker(job: IndexJob) -> None:
            await run_index_job(job, project_root=project_root, rag=rag)

        try:
            job = tracker.start_job(project_id=project.id, worker=_worker)
        except AlreadyIndexingError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        return IndexJobResponse(
            job_id=job.id, project_id=job.project_id, status=job.status
        )
```

- [ ] **Step 4: Run the index-route tests**

```bash
pytest plugin/tests/test_routes_index.py -v -k "post_index"
```

Expected: 4 passed. (The `test_post_index_202_and_job_transitions_to_done` test polls the status endpoint that does not yet exist — it will currently fail on the 404 from the status poll. Defer that test until Task 11 adds the status route.)

If the polling test fails for the above reason, mark it temporarily:

```python
@pytest.mark.skip(reason="status route added in Task 11")
def test_post_index_202_and_job_transitions_to_done(tmp_path, store):
    ...
```

Remove the skip in Task 11.

- [ ] **Step 5: Run the full suite + ruff**

```bash
ruff check .
pytest
```

Expected: **189 passed** (186 + 3 — the polling test is skipped until Task 11).

- [ ] **Step 6: Commit**

```bash
git add plugin/routes.py plugin/tests/test_routes_index.py
git commit -m "feat(plugin): add POST /projects/{id}/index route (202 + job_id + 409 guard)"
```

---

## Task 11: `GET /projects/{id}/index/status/{job_id}` route

**Files:**
- Modify: `plugin/routes.py`
- Modify: `plugin/tests/test_routes_index.py`

- [ ] **Step 1: Remove the `@pytest.mark.skip` from the polling test**

In `plugin/tests/test_routes_index.py`, find `test_post_index_202_and_job_transitions_to_done` (which was skipped in Task 10 if needed) and remove the `@pytest.mark.skip(...)` decorator.

- [ ] **Step 2: Append new status-only tests to `plugin/tests/test_routes_index.py`**

Append at the end of the file:

```python
def test_status_404_on_unknown_job(tmp_path, store):
    pid = _make_project(store, str(tmp_path))
    registry = _FakeRagRegistry(tmp_path / "rag")
    tracker = IndexJobTracker()
    c = _client(store, registry, tracker)
    r = c.get(f"/api/plugins/balu_code/projects/{pid}/index/status/nonexistent")
    assert r.status_code == 404


def test_status_404_when_job_belongs_to_different_project(tmp_path, store):
    from plugin.services.index_jobs import IndexJob

    _make_project(store, str(tmp_path))
    other_pid = _make_project(store, str(tmp_path / "sub"))

    registry = _FakeRagRegistry(tmp_path / "rag")
    tracker = IndexJobTracker()
    injected = IndexJob(id="j-other", project_id=9999, status=JobStatus.DONE)
    tracker._jobs["j-other"] = injected
    c = _client(store, registry, tracker)
    r = c.get(f"/api/plugins/balu_code/projects/{other_pid}/index/status/j-other")
    assert r.status_code == 404
```

- [ ] **Step 3: Run the tests and verify the polling test + new ones still fail**

```bash
pytest plugin/tests/test_routes_index.py -v
```

Expected: 3 failures (polling test + 2 new status tests — the route doesn't exist yet).

- [ ] **Step 4: Add the status handler in `plugin/routes.py`**

Inside `build_router`, right after `start_index_job` and before `return router`, append:

```python
    @router.get(
        "/projects/{project_id}/index/status/{job_id}",
        response_model=IndexStatusResponse,
        tags=["balu_code"],
    )
    async def index_job_status(
        project_id: int,
        job_id: str,
        _user: UserPublic = Depends(get_current_user),
        tracker: IndexJobTracker = Depends(get_index_job_tracker),
    ) -> IndexStatusResponse:
        job = tracker.get_job(job_id)
        if job is None or job.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"indexing job {job_id} not found for project {project_id}",
            )
        return IndexStatusResponse(
            job_id=job.id,
            project_id=job.project_id,
            status=job.status,
            files_total=job.files_total,
            files_processed=job.files_processed,
            chunks_total=job.chunks_total,
            error=job.error,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
```

- [ ] **Step 5: Run the route tests**

```bash
pytest plugin/tests/test_routes_index.py -v
```

Expected: **6 passed** (was 4 skipped-plus-rest; now polling + 2 new status cases all pass).

- [ ] **Step 6: Run the full suite + ruff**

```bash
ruff check .
ruff format --check .
pytest
```

Expected: **192 passed** (189 - 1 previously-skipped + 3 newly-passing).

(The exact count depends on whether the `@pytest.mark.skip` was actually applied in Task 10. The important thing is that all 6 tests in `test_routes_index.py` pass after Task 11, and the full suite stays green.)

- [ ] **Step 7: Commit**

```bash
git add plugin/routes.py plugin/tests/test_routes_index.py
git commit -m "feat(plugin): add GET /projects/{id}/index/status/{job_id} route"
```

---

## Task 12: Phase 3b verification + push

**Files:**
- Create: `docs/phase-3b-verification.md`

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
- pytest: ≥192 tests passing (record actual count).
- `dist/` contains `balu_code-0.1.0.bhplugin`, `.sha256`, `balu_code_cli-0.1.0-py3-none-any.whl`.

- [ ] **Step 2: Verify the `.bhplugin` includes the Phase 3b modules**

```bash
python -c "
import zipfile
with zipfile.ZipFile('dist/balu_code-0.1.0.bhplugin') as zf:
    names = sorted(zf.namelist())
want = {
    'services/rag_chunker.py',
    'services/rag_index.py',
    'services/rag_registry.py',
    'services/index_jobs.py',
    'services/indexer.py',
}
missing = want - set(names)
assert not missing, f'missing in .bhplugin: {missing}'
print('ok', len(names), 'files')
"
```

Expected: `ok <N> files`.

- [ ] **Step 3: Create `docs/phase-3b-verification.md`**

Replace bracketed values with your actual measurements. Use this template:

```markdown
# Phase 3b verification — 2026-04-19

## Environment (local dev)

- Commit: `<git rev-parse --short HEAD>`
- Python: 3.13.5 (CI matrix covers 3.11 & 3.12)

## Automated checks

- [x] `ruff check .` — clean
- [x] `ruff format --check .` — clean
- [x] `pytest -v` — `<N>` tests passing
- [x] `.bhplugin` includes `services/rag_chunker.py`, `services/rag_index.py`,
      `services/rag_registry.py`, `services/index_jobs.py`,
      `services/indexer.py`, plus prior Phase modules
- [x] `python -m scripts.build_wheel` still produces the CLI wheel
- [ ] GitHub Actions: CI green on `main` (fill in after push)

## Manual checks against dev BaluHost

- [ ] Re-sideload the new `.bhplugin` into
      `/opt/baluhost/backend/app/plugins/installed/balu_code/`
- [ ] BaluHost venv installs `sqlite-vec`
- [ ] Restart the BaluHost backend
- [ ] `POST /api/plugins/balu_code/projects/{id}/index` returns 202 + job_id
- [ ] `GET /api/plugins/balu_code/projects/{id}/index/status/{job_id}`
      transitions from `queued` → `running` → `done` with non-zero
      `files_processed` on a real Python project
- [ ] Re-POSTing while job is running returns 409

## Plan deviations

(List divergences encountered during the 12 tasks. Use
`git log --oneline 285a34e..HEAD` to enumerate commits — anything that
isn't a `feat:` matching a task title was a follow-up.)

## Known issues carried into Phase 4

- HTTP `/search` route not exposed (agent loop calls `RagIndex.search`
  as a service API; Phase 4/5 may add a debug route).
- Token approximation in repo-map + RAG retrieval is still `len // 4`;
  real tokenizer lands when Phase 4's agent loop needs it.
- No cross-process job persistence — server restart loses job state
  but indexed data survives in sqlite-vec.
- TypeScript / Go / Rust chunking still deferred.
```

- [ ] **Step 4: Commit + push**

```bash
git add docs/phase-3b-verification.md
git commit -m "docs: add Phase 3b verification checklist"
git push
```

- [ ] **Step 5: Verify CI on GitHub**

```bash
sleep 40
gh run list --limit 2
```

Expected: new run `completed success`. If `in_progress`, poll with `sleep 20 && gh run list --limit 2` up to ~3 min total. Once green, fill in the run URL in the verification doc and push a follow-up commit.

---

## Phase 3b Definition of Done

- All 12 tasks committed and pushed to `main`.
- CI green on `main` (both 3.11 and 3.12 matrix jobs).
- Full suite ≥192 tests, all green locally.
- `.bhplugin` archive includes all five new service modules.
- `POST /projects/{id}/index` returns 202 + job_id; status endpoint tracks progress; re-POST returns 409; search via `RagIndex.search` returns hits in the test suite.

## What comes next (not this plan)

- **Phase 4 — Agent loop + tools + WebSocket `/chat`.** `services/agent_loop.py`, tool registry, v1 tools, `WS /chat` streaming end-to-end, real tokenizer, smart ranker.
- **Phase 5 — CLI: `auth`, `init`, `models`, `index`, `chat` Textual TUI.**
- **Phase 6 — UI bundle + docs + release.**
