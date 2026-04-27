"""Tests for the indexer worker."""

from __future__ import annotations

import pytest

from plugin.services.index_jobs import IndexJob, JobStatus
from plugin.services.indexer import run_index_job


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


async def test_indexes_js_file(tmp_path, index):
    _write(tmp_path, "app.js", "function hello() { return 'hi'; }\n")
    job = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job, project_root=tmp_path, rag=index)
    assert job.status == JobStatus.DONE
    assert job.files_processed == 1
    assert "app.js" in await index.all_indexed_paths()


async def test_indexes_ts_file(tmp_path, index):
    _write(
        tmp_path,
        "utils.ts",
        "export function add(a: number, b: number): number { return a + b; }\n",
    )
    job = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job, project_root=tmp_path, rag=index)
    assert job.files_processed == 1
    assert "utils.ts" in await index.all_indexed_paths()


async def test_indexes_tsx_file(tmp_path, index):
    _write(tmp_path, "App.tsx", "export default function App() { return null; }\n")
    job = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job, project_root=tmp_path, rag=index)
    assert job.files_processed == 1
    assert "App.tsx" in await index.all_indexed_paths()


async def test_indexes_mixed_py_ts_directory(tmp_path, index):
    _write(tmp_path, "main.py", "def run(): pass\n")
    _write(tmp_path, "utils.ts", "export const PI = 3.14;\n")
    _write(tmp_path, "App.tsx", "export default function App() { return null; }\n")
    job = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job, project_root=tmp_path, rag=index)
    assert job.files_processed == 3
    paths = await index.all_indexed_paths()
    assert {"main.py", "utils.ts", "App.tsx"} <= paths
