"""In-memory tracker for indexing jobs.

A job is a UUID-tagged ``IndexJob`` with status / progress fields that
the worker coroutine mutates in place. ``start_job`` spawns the worker
as an ``asyncio.Task`` wrapped in a shim that catches exceptions and
finalises the status. One job per project at a time — concurrent starts
raise ``AlreadyIndexingError``.

When a ``db_path`` is supplied the tracker also persists job state to a
SQLite file so that other uvicorn workers (separate processes) can answer
status queries for jobs they did not start.  All fields including progress
counts are written on job finish.  Tests omit ``db_path`` and stay fully
in-memory.
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class JobStatus(StrEnum):
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
_MAX_FINISHED_JOBS = 50


class IndexJobTracker:
    def __init__(self, db_path: Path | None = None) -> None:
        self._jobs: dict[str, IndexJob] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._db_path = db_path
        if db_path is not None:
            self._init_db()

    # ------------------------------------------------------------------
    # SQLite helpers (only used when db_path is set)
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS indexing_jobs (
                    id               TEXT PRIMARY KEY,
                    project_id       INTEGER NOT NULL,
                    status           TEXT NOT NULL,
                    files_total      INTEGER DEFAULT 0,
                    files_processed  INTEGER DEFAULT 0,
                    chunks_total     INTEGER DEFAULT 0,
                    error            TEXT,
                    started_at       TEXT,
                    finished_at      TEXT
                )
            """)
            # Migrate existing DBs that predate the progress columns.
            existing = {row[1] for row in conn.execute("PRAGMA table_info(indexing_jobs)")}
            for col, defn in (
                ("files_total", "INTEGER DEFAULT 0"),
                ("files_processed", "INTEGER DEFAULT 0"),
                ("chunks_total", "INTEGER DEFAULT 0"),
            ):
                if col not in existing:
                    conn.execute(f"ALTER TABLE indexing_jobs ADD COLUMN {col} {defn}")

    def _db_upsert(self, job: IndexJob) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                INSERT INTO indexing_jobs
                    (id, project_id, status, files_total, files_processed, chunks_total,
                     error, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status          = excluded.status,
                    files_total     = excluded.files_total,
                    files_processed = excluded.files_processed,
                    chunks_total    = excluded.chunks_total,
                    error           = excluded.error,
                    finished_at     = excluded.finished_at
                """,
                (
                    job.id,
                    job.project_id,
                    job.status,
                    job.files_total,
                    job.files_processed,
                    job.chunks_total,
                    job.error,
                    job.started_at,
                    job.finished_at,
                ),
            )

    def _db_get(self, job_id: str) -> IndexJob | None:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM indexing_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return IndexJob(
            id=row["id"],
            project_id=row["project_id"],
            status=JobStatus(row["status"]),
            files_total=row["files_total"],
            files_processed=row["files_processed"],
            chunks_total=row["chunks_total"],
            error=row["error"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def _db_has_live(self, project_id: int) -> bool:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM indexing_jobs WHERE project_id = ? AND status IN ('queued','running') LIMIT 1",
                (project_id,),
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        if self._db_path is not None:
            self._db_upsert(job)
        task = asyncio.create_task(self._run(job, worker))
        task.add_done_callback(lambda _: self._tasks.pop(job.id, None))
        self._tasks[job.id] = task
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
            if self._db_path is not None:
                self._db_upsert(job)
            self._purge()

    def _purge(self) -> None:
        """Cancel done asyncio tasks and cap finished-job history."""
        done_task_ids = [jid for jid, t in self._tasks.items() if t.done()]
        for jid in done_task_ids:
            self._tasks.pop(jid, None)
        finished = [jid for jid, j in self._jobs.items() if j.status not in _LIVE]
        for jid in finished[:-_MAX_FINISHED_JOBS]:
            self._jobs.pop(jid)

    def get_job(self, job_id: str) -> IndexJob | None:
        job = self._jobs.get(job_id)
        if job is not None:
            return job
        if self._db_path is not None:
            return self._db_get(job_id)
        return None

    def is_running_for_project(self, project_id: int) -> bool:
        if any(j.project_id == project_id and j.status in _LIVE for j in self._jobs.values()):
            return True
        if self._db_path is not None:
            return self._db_has_live(project_id)
        return False


__all__ = [
    "AlreadyIndexingError",
    "IndexJob",
    "IndexJobTracker",
    "JobStatus",
]
