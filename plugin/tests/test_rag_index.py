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


async def test_upsert_empty_chunk_list_inserts_nothing(index):
    """Empty chunks + no prior rows → index stays empty."""
    await index.upsert_file_chunks("nothing.py", "sha1", [])
    assert "nothing.py" not in await index.all_indexed_paths()


async def test_upsert_empty_chunk_list_clears_existing_rows(index):
    """Empty chunks + prior rows for the same path → rows are deleted."""
    await index.upsert_file_chunks(
        "shrinking.py",
        "sha_before",
        [Chunk(file_path="shrinking.py", start_line=1, end_line=3, text="original body")],
    )
    assert await index.get_file_sha1("shrinking.py") == "sha_before"

    await index.upsert_file_chunks("shrinking.py", "sha_after", [])
    assert await index.get_file_sha1("shrinking.py") is None
    assert "shrinking.py" not in await index.all_indexed_paths()


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
        [
            Chunk(
                file_path="authentication/helpers.py",
                start_line=1,
                end_line=5,
                text=generic_text,
            )
        ],
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
