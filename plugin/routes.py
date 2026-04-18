"""FastAPI router for the balu_code plugin.

Hosts every route under ``/api/plugins/balu_code/`` minus the prefix.
The route surface is grouped here so adding a new endpoint in later
phases is a single-file change.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.api.deps import get_current_user
from app.schemas.user import UserPublic
from fastapi import APIRouter, Depends, HTTPException, status

from plugin.deps import get_ollama_client, get_project_store
from plugin.schemas import (
    ModelsResponse,
    ProjectCreate,
    ProjectsResponse,
    RepoMapResponse,
)
from plugin.services.ollama_client import (
    OllamaClient,
    OllamaRateLimited,
    OllamaTimeoutError,
    OllamaUnreachable,
)
from plugin.services.project_store import (
    DuplicateProjectError,
    Project,
    ProjectNotFoundError,
    ProjectStore,
)
from plugin.services.repo_map import ProjectRootNotAccessible, RepoMap

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


def build_router() -> APIRouter:
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
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
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
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
    ) -> ProjectsResponse:
        projects = await asyncio.to_thread(store.list_projects)
        return ProjectsResponse(projects=projects)

    @router.get("/projects/{project_id}", response_model=Project, tags=["balu_code"])
    async def get_project(
        project_id: int,
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
    ) -> Project:
        try:
            return await asyncio.to_thread(store.get_project, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"project {project_id} not found",
            ) from exc

    @router.delete(
        "/projects/{project_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["balu_code"],
    )
    async def delete_project(
        project_id: int,
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
    ) -> None:
        try:
            await asyncio.to_thread(store.delete_project, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"project {project_id} not found",
            ) from exc

    @router.get("/models", response_model=ModelsResponse, tags=["balu_code"])
    async def list_models_route(
        _user: UserPublic = Depends(get_current_user),
        ollama: OllamaClient = Depends(get_ollama_client),
    ) -> ModelsResponse:
        try:
            models = await ollama.list_models()
        except OllamaUnreachable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"ollama unreachable: {exc}",
            ) from exc
        except OllamaTimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"ollama timeout: {exc}",
            ) from exc
        except OllamaRateLimited as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"ollama rate-limited: {exc}",
            ) from exc
        return ModelsResponse(models=models)

    @router.get(
        "/projects/{project_id}/repo_map",
        response_model=RepoMapResponse,
        tags=["balu_code"],
    )
    async def repo_map_route(
        project_id: int,
        budget: int = 6144,
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
    ) -> RepoMapResponse:
        try:
            project = await asyncio.to_thread(store.get_project, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"project {project_id} not found",
            ) from exc

        repo_map = RepoMap(
            project_root=Path(project.root_path),
            store=store,
            project_id=project.id,
        )

        try:
            files = await asyncio.to_thread(repo_map.walk_and_cache)
        except ProjectRootNotAccessible as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"project root not accessible: {exc}",
            ) from exc

        rendered = RepoMap.render(files, budget_tokens=budget)
        return RepoMapResponse(
            text=rendered.text,
            file_count=rendered.file_count,
            truncated_files=list(rendered.truncated_files),
            total_bytes=rendered.total_bytes,
        )

    return router


__all__ = ["build_router"]
