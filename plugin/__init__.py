"""Balu Code BaluHost plugin.

Loaded at BaluHost startup by PluginManager. Exposes a FastAPI router at
/api/plugins/balu_code/ (currently /health plus project and model routes).
Owns two singletons: a SQLite-backed ProjectStore and an async OllamaClient.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.api.deps import get_current_user
from app.plugins.base import PluginBase, PluginMetadata
from app.schemas.user import UserPublic
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from plugin.config import BaluCodePluginConfig
from plugin.data_dir import resolve_data_dir
from plugin.deps import (
    clear_singletons,
    get_project_store,
    set_singletons,
)
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import (
    DuplicateProjectError,
    Project,
    ProjectStore,
)

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    root_path: str = Field(..., min_length=1)
    config_yaml: str | None = None


class ProjectsResponse(BaseModel):
    projects: list[Project]


def _build_router() -> APIRouter:
    """Build the FastAPI router served under /api/plugins/balu_code."""
    router = APIRouter()

    @router.get("/health", tags=["balu_code"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "plugin": _MANIFEST["name"],
            "version": _MANIFEST["version"],
        }

    @router.post(
        "/projects",
        response_model=Project,
        status_code=status.HTTP_201_CREATED,
        tags=["balu_code"],
    )
    async def create_project(
        body: ProjectCreate,
        _user: UserPublic = Depends(get_current_user),  # noqa: B008
        store: ProjectStore = Depends(get_project_store),  # noqa: B008
    ) -> Project:
        if not os.path.isabs(body.root_path):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="root_path must be absolute",
            )
        try:
            return await asyncio.to_thread(
                store.create_project, body.name, body.root_path, body.config_yaml
            )
        except DuplicateProjectError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"project '{body.name}' already exists",
            ) from exc

    @router.get("/projects", response_model=ProjectsResponse, tags=["balu_code"])
    async def list_projects(
        _user: UserPublic = Depends(get_current_user),  # noqa: B008
        store: ProjectStore = Depends(get_project_store),  # noqa: B008
    ) -> ProjectsResponse:
        projects = await asyncio.to_thread(store.list_projects)
        return ProjectsResponse(projects=projects)

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
        store = ProjectStore(data_dir / "store.db")
        try:
            ollama = OllamaClient(base_url=self._config.ollama_base_url)
        except BaseException:
            store.close()
            raise
        self._store = store
        self._ollama = ollama
        set_singletons(store, ollama)

    async def on_shutdown(self) -> None:
        if self._store is None and self._ollama is None:
            # on_startup was never called (or a previous shutdown already ran);
            # don't touch the module globals — they may belong to another instance.
            return
        if self._ollama is not None:
            await self._ollama.close()
        if self._store is not None:
            self._store.close()
        clear_singletons()
        self._store = None
        self._ollama = None


__all__ = ["BaluCodePlugin"]
