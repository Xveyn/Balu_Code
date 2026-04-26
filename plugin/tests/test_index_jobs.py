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


async def _wait_for_status(
    tracker: IndexJobTracker, job_id: str, target: JobStatus, timeout: float = 2.0
):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
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


async def test_completed_jobs_purged_when_limit_exceeded(tracker):
    from plugin.services.index_jobs import _MAX_FINISHED_JOBS

    async def noop(job: IndexJob) -> None:
        pass

    first_id = None
    for _ in range(_MAX_FINISHED_JOBS + 5):
        j = tracker.start_job(project_id=1, worker=noop)
        if first_id is None:
            first_id = j.id
        await _wait_for_status(tracker, j.id, JobStatus.DONE)

    assert len(tracker._jobs) <= _MAX_FINISHED_JOBS
    assert tracker.get_job(first_id) is None  # oldest entry evicted
    assert len(tracker._tasks) == 0  # completed asyncio tasks cleaned up
