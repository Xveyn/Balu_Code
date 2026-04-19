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
                f"embedding float[{self._vector_dim}])"
            )
            conn.commit()
        except BaseException:
            conn.close()
            raise
        self._conn = conn

    async def close(self) -> None:
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
        embeddings = await self._ollama.embed(self._embed_model, [c.text for c in chunks])
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
