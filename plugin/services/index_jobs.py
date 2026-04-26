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
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


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
        return self._jobs.get(job_id)

    def is_running_for_project(self, project_id: int) -> bool:
        return any(j.project_id == project_id and j.status in _LIVE for j in self._jobs.values())


__all__ = [
    "AlreadyIndexingError",
    "IndexJob",
    "IndexJobTracker",
    "JobStatus",
]
