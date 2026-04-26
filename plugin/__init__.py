"""Balu Code BaluHost plugin.

Loaded at BaluHost startup by PluginManager. Exposes a FastAPI router
at /api/plugins/balu_code/ — see ``plugin/routes.py``. Owns seven
singletons: ProjectStore, OllamaClient, RagRegistry, IndexJobTracker,
ToolRegistry, BaluCodePluginConfig, AuditLogger.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.plugins.base import PluginBase, PluginMetadata
from app.services.audit import get_audit_logger_db
from fastapi import APIRouter

from plugin.config import BaluCodePluginConfig
from plugin.data_dir import resolve_data_dir
from plugin.deps import clear_singletons, set_singletons
from plugin.routes import build_router
from plugin.services.audit import AuditLogger
from plugin.services.index_jobs import IndexJobTracker
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore
from plugin.services.rag_registry import RagRegistry
from plugin.services.tools import ToolRegistry, default_registry

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


class BaluCodePlugin(PluginBase):
    """Main plugin class. Metadata read from plugin.json at import time."""

    def __init__(self) -> None:
        self._config = BaluCodePluginConfig()
        self._store: ProjectStore | None = None
        self._ollama: OllamaClient | None = None
        self._rag_registry: RagRegistry | None = None
        self._index_job_tracker: IndexJobTracker | None = None
        self._tool_registry: ToolRegistry | None = None

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
        return build_router()

    def get_config_schema(self) -> type:
        return BaluCodePluginConfig

    def get_default_config(self) -> dict:
        return BaluCodePluginConfig().model_dump()

    async def on_startup(self) -> None:
        data_dir = resolve_data_dir()
        store = ProjectStore(data_dir / "store.db")
        try:
            ollama = OllamaClient(base_url=self._config.ollama_base_url)
        except BaseException:
            store.close()
            raise
        rag_registry = RagRegistry(
            data_dir=data_dir,
            embed_model=self._config.embed_model,
            ollama=ollama,
        )
        index_job_tracker = IndexJobTracker()
        tool_registry = default_registry()
        audit_log = AuditLogger(get_audit_logger_db())
        self._store = store
        self._ollama = ollama
        self._rag_registry = rag_registry
        self._index_job_tracker = index_job_tracker
        self._tool_registry = tool_registry
        set_singletons(
            store,
            ollama,
            rag_registry,
            index_job_tracker,
            tool_registry,
            self._config,
            audit_log,
        )

    async def on_shutdown(self) -> None:
        if (
            self._store is None
            and self._ollama is None
            and self._rag_registry is None
            and self._index_job_tracker is None
            and self._tool_registry is None
        ):
            return
        if self._rag_registry is not None:
            await self._rag_registry.close_all()
        if self._ollama is not None:
            await self._ollama.close()
        if self._store is not None:
            self._store.close()
        clear_singletons()
        self._store = None
        self._ollama = None
        self._rag_registry = None
        self._index_job_tracker = None
        self._tool_registry = None


__all__ = ["BaluCodePlugin"]
