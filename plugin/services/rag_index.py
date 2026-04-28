"""Per-project sqlite-vec index for chunk embeddings.

One RagIndex instance per project; the registry (``rag_registry.py``)
owns the map. The DB file is self-contained: ``project_id`` lives in
the filename, not in the rows, so an index is dropped by deleting one
file.

All blocking sqlite3 work runs inside ``asyncio.to_thread``; the public
API is async so callers can ``await`` without remembering the
thread-dispatch dance per-call.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec

from .ollama_client import OllamaClient
from .rag_chunker import Chunk

_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)

# nomic-embed-text has an 8 192-token context window. At ~4 chars/token that's
# ~32 K chars. 30 K gives a comfortable margin and also fits smaller models.
_MAX_EMBED_CHARS = 30_000


def _keyword_tokens(query: str) -> set[str]:
    """Lowercased tokens of length >=3 extracted from ``query``."""
    return {t.lower() for t in _TOKEN_RE.findall(query) if len(t) >= 3}


def _has_token(tokens: set[str], file_path: str, text: str) -> bool:
    hay = (file_path + "\n" + text).lower()
    return any(t in hay for t in tokens)


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
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._open_sync)

    def _open_sync(self) -> None:
        if self._conn is not None:
            return  # already open — idempotent
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        try:
            try:
                sqlite_vec.load(conn)
            except Exception as exc:
                raise RagIndexUnavailable(f"sqlite-vec failed to load: {exc}") from exc
            conn.enable_load_extension(False)
            conn.executescript(_SCHEMA)
            # vec0 virtual table: create separately because vec0 doesn't like being
            # inside an executescript that also has other CREATE TABLE statements.
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
                f"embedding float[{self._vector_dim}] distance_metric=cosine)"
            )
            conn.commit()
        except BaseException:
            conn.close()
            raise
        self._conn = conn

    async def close(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def upsert_file_chunks(self, file_path: str, file_sha1: str, chunks: list[Chunk]) -> None:
        """Replace this file's chunks.

        If ``chunks`` is empty, existing rows for ``file_path`` are removed
        and no new rows are inserted. This keeps the index self-consistent
        when a file shrinks to zero chunkable content (e.g. becomes empty
        or contains only whitespace).
        """
        if not chunks:
            await self.delete_file_chunks(file_path)
            return
        # Cap each chunk to _MAX_EMBED_CHARS before embedding to avoid context-length
        # errors. nomic-embed-text has an 8192-token context; at ~4 chars/token that's
        # ~32 K chars. We use 30 K to leave headroom for models with smaller contexts.
        texts = [c.text[:_MAX_EMBED_CHARS] for c in chunks]
        embeddings = await self._ollama.embed(self._embed_model, texts)
        async with self._lock:
            await asyncio.to_thread(self._upsert_sync, file_path, file_sha1, chunks, embeddings)

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
                    f"DELETE FROM chunks WHERE id IN ({placeholders})",
                    old_ids,
                )
                conn.execute(
                    f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})",
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
        async with self._lock:
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
                f"DELETE FROM chunks WHERE id IN ({placeholders})",
                ids,
            )
            conn.execute(
                f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})",
                ids,
            )

    async def get_file_sha1(self, file_path: str) -> str | None:
        async with self._lock:
            return await asyncio.to_thread(self._get_file_sha1_sync, file_path)

    def _get_file_sha1_sync(self, file_path: str) -> str | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT file_sha1 FROM chunks WHERE file_path = ? LIMIT 1", (file_path,)
        ).fetchone()
        return row[0] if row is not None else None

    async def all_indexed_paths(self) -> set[str]:
        async with self._lock:
            return await asyncio.to_thread(self._all_paths_sync)

    def _all_paths_sync(self) -> set[str]:
        assert self._conn is not None
        return {row[0] for row in self._conn.execute("SELECT DISTINCT file_path FROM chunks")}

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
        async with self._lock:
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


__all__ = [
    "RagIndex",
    "RagIndexError",
    "RagIndexUnavailable",
    "SearchHit",
]
