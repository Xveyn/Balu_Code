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
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from .config import BaluCodePluginConfig
from .deps import (
    get_audit_log,
    get_data_dir,
    get_ollama_client,
    get_opencode_password,
    get_plugin_config,
    get_project_store,
    update_plugin_config,
)
from .schemas import (
    ApprovalSummary,
    ChatV2Request,
    ConfigUpdateRequest,
    DayStat,
    GpuInfo,
    LoadedModel,
    LogEntry,
    LogsResponse,
    ModelsResponse,
    ModelStat,
    OllamaSystemInfo,
    ProjectCreate,
    ProjectsResponse,
    RepoMapResponse,
    RuntimeCredentialsResponse,
    RuntimeStatusResponse,
    StatsResponse,
    SystemResponse,
    ToolStat,
)
from .services.config_store import save_plugin_config
from .services.ollama_client import (
    OllamaClient,
    OllamaRateLimited,
    OllamaTimeoutError,
    OllamaUnreachable,
)
from .services.ollama_proxy import proxy_request
from .services.opencode_runtime import OPENCODE_VERSION
from .services.project_store import (
    DuplicateProjectError,
    Project,
    ProjectNotFoundError,
    ProjectStore,
)
from .services.repo_map import ProjectRootNotAccessible, RepoMap
from .services.session_bridge import SessionBridge
from .services.system import get_gpu_info

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


def _split_model(model_str: str) -> tuple[str, str]:
    """Split "provider/modelID" into (provider, modelID).
    If no slash, defaults provider to 'ollama'."""
    if "/" in model_str:
        provider, _, mid = model_str.partition("/")
        return provider, mid
    return "ollama", model_str


def _session_bridge() -> SessionBridge:
    from .deps import get_opencode_client as _goc
    from .deps import get_project_store as _gps

    return SessionBridge(
        store=_gps(),
        create_session=_goc().create_session,
    )


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

    @router.get("/config", response_model=BaluCodePluginConfig, tags=["balu_code"])
    async def get_config_route(
        _user: UserPublic = Depends(get_current_user),
        config: BaluCodePluginConfig = Depends(get_plugin_config),
    ) -> BaluCodePluginConfig:
        return config

    @router.put("/config", response_model=BaluCodePluginConfig, tags=["balu_code"])
    async def put_config_route(
        body: ConfigUpdateRequest,
        _user: UserPublic = Depends(get_current_user),
        config: BaluCodePluginConfig = Depends(get_plugin_config),
        data_dir: Path = Depends(get_data_dir),
    ) -> BaluCodePluginConfig:
        merged = config.model_dump()
        merged.update(body.model_dump(exclude_none=True))
        new_config = BaluCodePluginConfig.model_validate(merged)
        await asyncio.to_thread(save_plugin_config, new_config, data_dir)
        update_plugin_config(new_config)
        return new_config

    @router.get("/logs", response_model=LogsResponse, tags=["balu_code"])
    async def get_logs_route(
        limit: int = Query(default=100, ge=1, le=500),
        _user: UserPublic = Depends(get_current_user),
        audit_log=Depends(get_audit_log),
    ) -> LogsResponse:
        raw = await audit_log.query_recent_tool_calls(limit)
        return LogsResponse(entries=[LogEntry.model_validate(d) for d in raw])

    @router.get("/system", response_model=SystemResponse, tags=["balu_code"])
    async def get_system_route(
        _user: UserPublic = Depends(get_current_user),
        ollama: OllamaClient = Depends(get_ollama_client),
    ) -> SystemResponse:
        loaded_raw, gpu_raw = await asyncio.gather(
            ollama.ps(),
            asyncio.to_thread(get_gpu_info),
        )
        loaded = [LoadedModel(**m) for m in loaded_raw]
        ollama_info = OllamaSystemInfo(reachable=True, loaded_models=loaded)
        gpu_info = GpuInfo(available=False) if gpu_raw is None else GpuInfo(**gpu_raw)
        return SystemResponse(ollama=ollama_info, gpu=gpu_info)

    @router.get("/stats", response_model=StatsResponse, tags=["balu_code"])
    async def get_stats_route(
        days: int = Query(default=7, ge=1, le=90),
        _user: UserPublic = Depends(get_current_user),
        audit_log=Depends(get_audit_log),
    ) -> StatsResponse:
        raw = await audit_log.query_stats(days=days)
        return StatsResponse(
            last_n_days=[DayStat(**d) for d in raw["last_n_days"]],
            by_model=[ModelStat(**m) for m in raw["by_model"]],
            top_tools=[ToolStat(**t) for t in raw["top_tools"]],
            approval_summary=ApprovalSummary(**raw["approval_summary"]),
        )

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
        response_model=None,
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

    @router.get(
        "/projects/{project_id}/repo_map",
        response_model=RepoMapResponse,
        tags=["balu_code"],
    )
    async def get_repo_map_route(
        project_id: int,
        budget: int = Query(default=2048, ge=64, le=32768),
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
        repo_map = RepoMap(Path(project.root_path), store, project_id)
        try:
            files = await asyncio.to_thread(repo_map.walk_and_cache)
        except ProjectRootNotAccessible as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"project root not accessible: {exc}",
            ) from exc
        rendered = RepoMap.render(files, budget_tokens=budget, project_name=project.name)
        return RepoMapResponse(
            text=rendered.text,
            file_count=rendered.file_count,
            truncated_files=rendered.truncated_files,
            total_bytes=rendered.total_bytes,
        )

    @router.post(
        "/projects/{project_id}/repo_map/rebuild",
        response_model=RepoMapResponse,
        tags=["balu_code"],
    )
    async def rebuild_repo_map_route(
        project_id: int,
        budget: int = Query(default=2048, ge=64, le=32768),
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
        # Drop the entire cache for this project, then walk afresh.
        await asyncio.to_thread(store.delete_repo_map_entries, project_id, set())
        repo_map = RepoMap(Path(project.root_path), store, project_id)
        try:
            files = await asyncio.to_thread(repo_map.walk_and_cache)
        except ProjectRootNotAccessible as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"project root not accessible: {exc}",
            ) from exc
        rendered = RepoMap.render(files, budget_tokens=budget, project_name=project.name)
        return RepoMapResponse(
            text=rendered.text,
            file_count=rendered.file_count,
            truncated_files=rendered.truncated_files,
            total_bytes=rendered.total_bytes,
        )

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

    # ----- /chat/v2: opencode-backed chat (sync, JSON) -----
    @router.post("/chat/v2/{project_id}", tags=["balu_code"])
    async def chat_v2(project_id: int, body: ChatV2Request):
        from .deps import get_audit_log, get_opencode_client, get_plugin_config

        client = get_opencode_client()
        audit = get_audit_log()
        bridge = _session_bridge()
        session_id = await bridge.get_or_create(project_id)

        # Extract last user message text
        last_user = next(
            (m for m in reversed(body.messages) if m.role == "user"),
            None,
        )
        if last_user is None:
            raise HTTPException(status_code=400, detail="messages must include a user message")

        model_str = body.model or f"ollama/{get_plugin_config().chat_model}"
        provider, model_id = _split_model(model_str)

        # Assemble prompt text: prepend the repo-map envelope (if enabled +
        # the project root exists) so opencode/qwen-coder starts each turn
        # with file/symbol awareness instead of having to grep.
        prompt_text = last_user.content
        config = get_plugin_config()
        if config.repo_map_enabled:
            store = get_project_store()
            try:
                project = await asyncio.to_thread(store.get_project, project_id)
                repo_map = RepoMap(Path(project.root_path), store, project_id)
                files = await asyncio.to_thread(repo_map.walk_and_cache)
                rendered = RepoMap.render(
                    files,
                    budget_tokens=config.repo_map_budget,
                    project_name=project.name,
                )
                prompt_text = (
                    f"{rendered.text}\n\n" f"<user_message>\n{last_user.content}\n</user_message>"
                )
            except (ProjectNotFoundError, ProjectRootNotAccessible):
                # Silently degrade — chat still works without the map.
                prompt_text = last_user.content

        result = await client.prompt(
            session_id,
            text=prompt_text,
            model_provider=provider,
            model_id=model_id,
        )

        # Audit any tool parts
        for part in result.get("parts", []):
            if part.get("type") == "tool" and part.get("tool"):
                state = part.get("state") or {}
                tool_status = state.get("status", "completed")
                await audit.record_tool_call(
                    tool=part.get("tool", "unknown"),
                    user="system",  # Phase B: thread real user identity
                    turn_id=session_id,
                    tool_call_id=part.get("callID", part.get("id", "")),
                    args=part.get("input", {}),
                    status="ok" if tool_status == "completed" else "error",
                    bytes_out=0,
                    error=None if tool_status == "completed" else state.get("error"),
                    approved=True,
                    auto_approved=True,
                )

        return result

    @router.post("/chat/v2/{project_id}/cancel", tags=["balu_code"])
    async def chat_v2_cancel(project_id: int):
        from .deps import get_opencode_client

        client = get_opencode_client()
        bridge = _session_bridge()
        session_id = await bridge.get_or_create(project_id)
        await client.session_abort(session_id)
        return {"status": "aborted"}

    @router.get("/runtime/status", response_model=RuntimeStatusResponse, tags=["balu_code"])
    async def runtime_status():
        from .deps import get_opencode_client, get_opencode_handle

        handle = get_opencode_handle()
        client = get_opencode_client()
        healthy = await client.health()
        return RuntimeStatusResponse(
            healthy=healthy,
            port=handle.port,
            pid=handle.pid,
            binary_version=OPENCODE_VERSION,
        )

    @router.post("/runtime/restart", tags=["balu_code"])
    async def runtime_restart():
        raise HTTPException(
            status_code=501,
            detail="manual restart not implemented; rely on watchdog",
        )

    @router.get(
        "/runtime/credentials",
        response_model=RuntimeCredentialsResponse,
        tags=["balu_code"],
    )
    def runtime_credentials(
        _user: UserPublic = Depends(get_current_user),
    ) -> RuntimeCredentialsResponse:
        try:
            password = get_opencode_password()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="opencode runtime not initialized",
            ) from exc
        return RuntimeCredentialsResponse(username="opencode", password=password)

    @router.api_route(
        "/ollama/{path:path}",
        methods=["GET", "POST"],
        tags=["balu_code"],
    )
    async def ollama_proxy_route(
        path: str,
        request: Request,
        _user: UserPublic = Depends(get_current_user),
        config: BaluCodePluginConfig = Depends(get_plugin_config),
    ):
        return await proxy_request(request, path, base_url=config.ollama_base_url)

    return router


__all__ = ["build_router"]
