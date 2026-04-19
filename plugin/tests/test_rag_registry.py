"""Tests for RagRegistry."""
from __future__ import annotations

import pytest

from plugin.services.rag_registry import RagRegistry


class _FakeOllama:
    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 768 for _ in texts]

    async def close(self) -> None:
        pass


@pytest.fixture
def registry(tmp_path) -> RagRegistry:
    return RagRegistry(
        data_dir=tmp_path,
        embed_model="nomic-embed-text",
        ollama=_FakeOllama(),
    )


async def test_get_opens_index_on_first_call(registry, tmp_path):
    idx = await registry.get(1)
    assert idx is not None
    assert (tmp_path / "indices" / "project_1.db").exists()


async def test_get_returns_same_instance_for_same_project(registry):
    a = await registry.get(1)
    b = await registry.get(1)
    assert a is b


async def test_get_returns_distinct_instance_per_project(registry):
    idx1 = await registry.get(1)
    idx2 = await registry.get(2)
    assert idx1 is not idx2


async def test_close_all_closes_every_open_index(registry):
    await registry.get(1)
    await registry.get(2)
    await registry.close_all()
    # After close_all, subsequent get re-opens (and doesn't raise).
    idx = await registry.get(1)
    assert idx is not None
