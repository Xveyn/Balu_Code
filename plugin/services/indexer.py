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
        sha1 = hashlib.sha1(content_bytes).hexdigest()
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
