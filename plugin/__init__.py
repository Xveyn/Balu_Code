"""Balu Code BaluHost plugin.

Loaded at BaluHost startup by PluginManager. Exposes a FastAPI router
at /api/plugins/balu_code/ — see ``plugin/routes.py``. Owns singletons:
ProjectStore, OllamaClient, BaluCodePluginConfig, AuditLogger, and the
embedded opencode runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.plugins.base import PluginBase, PluginMetadata
from app.services.audit import get_audit_logger_db
from fastapi import APIRouter

from .config import BaluCodePluginConfig
from .data_dir import resolve_data_dir
from .deps import clear_opencode, clear_singletons, set_singletons
from .routes import build_router
from .services.audit import AuditLogger
from .services.ollama_client import OllamaClient
from .services.project_store import ProjectStore

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


class BaluCodePlugin(PluginBase):
    """Main plugin class. Metadata read from .json at import time."""

    def __init__(self) -> None:
        self._config = BaluCodePluginConfig()
        self._store: ProjectStore | None = None
        self._ollama: OllamaClient | None = None
        self._opencode_handle = None
        self._opencode_client = None

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

    def get_ui_manifest(self):
        from app.plugins.base import PluginNavItem, PluginUIManifest

        return PluginUIManifest(
            enabled=True,
            bundle_path="bundle.js",
            nav_items=[
                PluginNavItem(path="/", label="Balu Code", icon="code-2", order=10),
            ],
        )

    async def on_startup(self) -> None:
        from .services.config_store import load_plugin_config

        data_dir = resolve_data_dir()
        self._config = load_plugin_config(data_dir)
        store = ProjectStore(data_dir / "store.db")
        try:
            ollama = OllamaClient(base_url=self._config.ollama_base_url)
        except BaseException:
            store.close()
            raise
        audit_log = AuditLogger(get_audit_logger_db())
        self._store = store
        self._ollama = ollama
        set_singletons(
            store,
            ollama,
            self._config,
            audit_log,
            data_dir,
        )

        # Boot the embedded opencode runtime.
        # CWD defaults to data_dir; routes may restart opencode in a project's
        # root_path when a different project becomes active (single-server
        # single-current-project model — see spec section "Plan deviations").
        from .deps import set_opencode, set_opencode_password
        from .services.opencode_client import OpencodeClient
        from .services.opencode_config import write_opencode_config
        from .services.opencode_runtime import ensure_binary, start_or_attach_server
        from .services.runtime_password import load_or_create_password

        # Phase A: treat as allowed; Phase B wires the real BaluHost permission check.
        file_write_allowed = True

        opencode_binary = await ensure_binary(data_dir)
        opencode_cfg_path = write_opencode_config(
            data_dir, self._config, file_write_allowed=file_write_allowed
        )
        opencode_log_path = data_dir / "opencode.log"
        opencode_password = load_or_create_password(data_dir)
        set_opencode_password(opencode_password)
        handle = await start_or_attach_server(
            binary=opencode_binary,
            config_dir=opencode_cfg_path.parent,  # OPENCODE_CONFIG_DIR
            log_path=opencode_log_path,
            lock_path=data_dir / "runtime.lock",
            port=self._config.opencode_port,
            ready_timeout=20.0,
            password=opencode_password,
        )
        opencode_client = OpencodeClient(
            f"http://127.0.0.1:{handle.port}", password=opencode_password
        )
        set_opencode(handle, opencode_client)
        self._opencode_handle = handle
        self._opencode_client = opencode_client

    async def on_shutdown(self) -> None:
        # Stop the embedded opencode runtime first
        from .services.opencode_runtime import stop_server

        if self._opencode_client is not None:
            await self._opencode_client.close()
        if self._opencode_handle is not None:
            await stop_server(self._opencode_handle)
        clear_opencode()
        self._opencode_handle = None
        self._opencode_client = None

        if self._store is None and self._ollama is None:
            return
        if self._ollama is not None:
            await self._ollama.close()
        if self._store is not None:
            self._store.close()
        clear_singletons()
        self._store = None
        self._ollama = None


__all__ = ["BaluCodePlugin"]
