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
from datetime import UTC, datetime
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
    opencode_session_id: str | None = None


class RepoMapCacheRow(BaseModel):
    project_id: int
    file_path: str
    mtime: float
    sha1: str
    symbols_json: str


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

_MIGRATIONS = [
    "ALTER TABLE projects ADD COLUMN opencode_session_id TEXT",
]


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Idempotent column adds. sqlite has no IF NOT EXISTS for columns."""
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise
    conn.commit()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ProjectStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
            _apply_migrations(self._conn)

    def create_project(self, name: str, root_path: str, config_yaml: str | None) -> Project:
        now = _now_iso()
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO projects (name, root_path, config_yaml, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (name, root_path, config_yaml, now, now),
                )
                self._conn.commit()
                project_id = cur.lastrowid
            except sqlite3.IntegrityError as exc:
                if exc.sqlite_errorname == "SQLITE_CONSTRAINT_UNIQUE":
                    raise DuplicateProjectError(name) from exc
                raise
        return Project(
            id=project_id,
            name=name,
            root_path=root_path,
            config_yaml=config_yaml,
            created_at=now,
            updated_at=now,
            opencode_session_id=None,
        )

    def list_projects(self) -> list[Project]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, root_path, config_yaml, created_at, updated_at, opencode_session_id "
                "FROM projects ORDER BY id ASC"
            ).fetchall()
        return [Project(**dict(r)) for r in rows]

    def get_project(self, project_id: int) -> Project:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, name, root_path, config_yaml, created_at, updated_at, opencode_session_id "
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
            deleted = cur.rowcount
        if deleted == 0:
            raise ProjectNotFoundError(project_id)

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

    def delete_repo_map_entries(self, project_id: int, paths_to_keep: set[str]) -> None:
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
                    f"DELETE FROM repo_map_cache WHERE project_id = ? "
                    f"AND file_path NOT IN ({placeholders})",
                    params,
                )
            self._conn.commit()

    def set_opencode_session_id(self, project_id: int, session_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE projects SET opencode_session_id = ?, updated_at = ? WHERE id = ?",
                (session_id, _now_iso(), project_id),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = [
    "DuplicateProjectError",
    "Project",
    "ProjectNotFoundError",
    "ProjectStore",
    "ProjectStoreError",
    "RepoMapCacheRow",
]
