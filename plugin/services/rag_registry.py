"""Per-plugin registry of RagIndex instances, one per project.

Indices are opened lazily on first access and cached. On plugin
shutdown the registry closes every opened index.

Concurrency: ``get`` is guarded by an ``asyncio.Lock`` so two
simultaneous requests for the same project cannot double-open the DB.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from plugin.services.ollama_client import OllamaClient
from plugin.services.rag_index import RagIndex


class RagRegistry:
    def __init__(
        self,
        data_dir: Path,
        embed_model: str,
        ollama: OllamaClient,
    ) -> None:
        self._data_dir = data_dir
        self._embed_model = embed_model
        self._ollama = ollama
        self._indices: dict[int, RagIndex] = {}
        self._lock = asyncio.Lock()

    async def get(self, project_id: int) -> RagIndex:
        async with self._lock:
            idx = self._indices.get(project_id)
            if idx is not None:
                return idx
            db_path = self._data_dir / "indices" / f"project_{project_id}.db"
            new_idx = RagIndex(
                db_path=db_path,
                embed_model=self._embed_model,
                ollama=self._ollama,
            )
            await new_idx.open()
            self._indices[project_id] = new_idx
            return new_idx

    async def close_all(self) -> None:
        async with self._lock:
            for idx in self._indices.values():
                await idx.close()
            self._indices.clear()


__all__ = ["RagRegistry"]
