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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ProjectStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def create_project(
        self, name: str, root_path: str, config_yaml: str | None
    ) -> Project:
        now = _now_iso()
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO projects (name, root_path, config_yaml, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (name, root_path, config_yaml, now, now),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise DuplicateProjectError(name) from exc
                raise
        project_id = cur.lastrowid
        return Project(
            id=project_id,
            name=name,
            root_path=root_path,
            config_yaml=config_yaml,
            created_at=now,
            updated_at=now,
        )

    def list_projects(self) -> list[Project]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, root_path, config_yaml, created_at, updated_at "
                "FROM projects ORDER BY id ASC"
            ).fetchall()
        return [Project(**dict(r)) for r in rows]

    def get_project(self, project_id: int) -> Project:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, name, root_path, config_yaml, created_at, updated_at "
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
        if cur.rowcount == 0:
            raise ProjectNotFoundError(project_id)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = [
    "DuplicateProjectError",
    "Project",
    "ProjectNotFoundError",
    "ProjectStore",
    "ProjectStoreError",
]
