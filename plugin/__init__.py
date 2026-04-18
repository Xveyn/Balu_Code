"""Balu Code BaluHost plugin.

Loaded at BaluHost startup by PluginManager. Exposes a FastAPI router at
/api/plugins/balu_code/ (currently /health plus project and model routes).
Owns two singletons: a SQLite-backed ProjectStore and an async OllamaClient.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.plugins.base import PluginBase, PluginMetadata
from fastapi import APIRouter

from plugin.config import BaluCodePluginConfig
from plugin.data_dir import resolve_data_dir
from plugin.deps import clear_singletons, set_singletons
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


def _build_router() -> APIRouter:
    """Build the FastAPI router served under /api/plugins/balu_code.

    Routes land in later tasks; Phase 2 keeps only /health until Task 10.
    """
    router = APIRouter()

    @router.get("/health", tags=["balu_code"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "plugin": _MANIFEST["name"],
            "version": _MANIFEST["version"],
        }

    return router


class BaluCodePlugin(PluginBase):
    """Main plugin class. Metadata read from plugin.json at import time."""

    def __init__(self) -> None:
        self._config = BaluCodePluginConfig()
        self._store: ProjectStore | None = None
        self._ollama: OllamaClient | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=_MANIFEST["name"],
            version=_MANIFEST["version"],
            display_name=_MANIFEST["display_name"],
            description=_MANIFEST["description"],
            author=_MANIFEST["author"],
            required_permissions=list(_MANIFEST["required_permissions"]),
            category=_MANIFEST.get("category", "general"),
            homepage=_MANIFEST.get("homepage"),
            min_baluhost_version=_MANIFEST.get("min_baluhost_version"),
            dependencies=list(_MANIFEST.get("plugin_dependencies", [])),
        )

    def get_router(self) -> APIRouter:
        return _build_router()

    def get_config_schema(self) -> type:
        return BaluCodePluginConfig

    def get_default_config(self) -> dict:
        return BaluCodePluginConfig().model_dump()

    async def on_startup(self) -> None:
        data_dir = resolve_data_dir()
        self._store = ProjectStore(data_dir / "store.db")
        self._ollama = OllamaClient(base_url=self._config.ollama_base_url)
        set_singletons(self._store, self._ollama)

    async def on_shutdown(self) -> None:
        if self._ollama is not None:
            await self._ollama.close()
        if self._store is not None:
            self._store.close()
        clear_singletons()
        self._store = None
        self._ollama = None


__all__ = ["BaluCodePlugin"]
