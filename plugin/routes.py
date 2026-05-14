"""FastAPI router for the balu_code plugin.

Hosts every route under ``/api/plugins/balu_code/`` minus the prefix.
The route surface is grouped here so adding a new endpoint in later
phases is a single-file change.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC
from pathlib import Path

from app.api.deps import get_current_user
from app.core.database import get_db
from app.schemas.user import UserPublic
from app.services import auth as auth_service
from app.services import users as user_service
from balu_code_shared.events import Approval, Cancel, Error, UserMessage, parse_frame
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from .config import BaluCodePluginConfig
from .deps import (
    get_audit_log,
    get_data_dir,
    get_index_job_tracker,
    get_ollama_client,
    get_plugin_config,
    get_project_store,
    get_rag_registry,
    get_tool_registry,
    update_plugin_config,
)
from .schemas import (
    ApprovalSummary,
    ChatV2Request,
    ConfigUpdateRequest,
    DayStat,
    GpuInfo,
    IndexJobResponse,
    IndexStatusResponse,
    LoadedModel,
    LogEntry,
    LogsResponse,
    ModelsResponse,
    ModelStat,
    OllamaSystemInfo,
    ProjectCreate,
    ProjectsResponse,
    RepoMapResponse,
    StatsResponse,
    SystemResponse,
    ToolStat,
    TurnCurrentResponse,
)
from .services.agent_loop import TurnContext, TurnDeps, run_turn
from .services.cancel import CancelToken
from .services.config_store import save_plugin_config
from .services.index_jobs import (
    AlreadyIndexingError,
    IndexJob,
    IndexJobTracker,
)
from .services.indexer import run_index_job
from .services.ollama_client import (
    OllamaClient,
    OllamaRateLimited,
    OllamaTimeoutError,
    OllamaUnreachable,
)
from .services.project_store import (
    DuplicateProjectError,
    Project,
    ProjectNotFoundError,
    ProjectStore,
)
from .services.rag_index import RagIndexUnavailable
from .services.rag_registry import RagRegistry
from .services.repo_map import ProjectRootNotAccessible, RepoMap
from .services.session_bridge import SessionBridge
from .services.system import get_gpu_info
from .services.tools import ToolRegistry

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
    from .deps import get_opencode_client as _goc, get_project_store as _gps

    return SessionBridge(
        store=_gps(),
        create_session=_goc().create_session,
    )


async def _ws_auth(websocket: WebSocket) -> UserPublic:
    """Extract and validate Bearer token from a WebSocket connection.

    OAuth2PasswordBearer only works with HTTP Request objects, not WebSockets,
    so we replicate the token extraction and validation logic manually.
    """
    from app.services.api_key_service import ApiKeyService

    auth_header = websocket.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        await websocket.close(code=1008, reason="missing auth token")
        raise WebSocketDisconnect(code=1008)

    db = next(get_db())
    try:
        if token.startswith("balu_"):
            api_key = ApiKeyService.validate_api_key(db, token)
            if not api_key:
                await websocket.close(code=1008, reason="invalid api key")
                raise WebSocketDisconnect(code=1008)
            u = user_service.get_user(api_key.target_user_id, db=db)
            if not u or not u.is_active:
                await websocket.close(code=1008, reason="user inactive")
                raise WebSocketDisconnect(code=1008)
            return user_service.serialize_user(u)
        else:
            payload = auth_service.decode_token(token)
            u = user_service.get_user(payload.sub, db=db)
            if not u or not u.is_active:
                await websocket.close(code=1008, reason="user inactive")
                raise WebSocketDisconnect(code=1008)
            return user_service.serialize_user(u)
    finally:
        db.close()


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

    @router.get("/turns/current", response_model=TurnCurrentResponse, tags=["balu_code"])
    async def get_turns_current(
        _user: UserPublic = Depends(get_current_user),
    ) -> TurnCurrentResponse:
        from datetime import datetime

        from .services.active_turn import get_active

        turn = get_active()
        if turn is None:
            return TurnCurrentResponse(active=False)
        elapsed = int((datetime.now(UTC) - turn.started_at).total_seconds())
        return TurnCurrentResponse(
            active=True,
            turn_id=turn.turn_id,
            model=turn.model,
            started_at=turn.started_at.isoformat(),
            elapsed_seconds=elapsed,
            iterations=turn.iterations,
            username=turn.username,
        )

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
        budget: int = Query(default=6144, ge=64, le=32768),
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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"project root not accessible: {exc}",
            ) from exc

        rendered = RepoMap.render(files, budget_tokens=budget)
        return RepoMapResponse(
            text=rendered.text,
            file_count=rendered.file_count,
            truncated_files=list(rendered.truncated_files),
            total_bytes=rendered.total_bytes,
        )

    @router.post(
        "/projects/{project_id}/index",
        response_model=IndexJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["balu_code"],
    )
    async def start_index_job(
        project_id: int,
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
        rag_registry: RagRegistry = Depends(get_rag_registry),
        tracker: IndexJobTracker = Depends(get_index_job_tracker),
    ) -> IndexJobResponse:
        try:
            project = await asyncio.to_thread(store.get_project, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"project {project_id} not found",
            ) from exc

        try:
            rag = await rag_registry.get(project.id)
        except RagIndexUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"rag index unavailable: {exc}",
            ) from exc

        project_root = Path(project.root_path)

        async def _worker(job: IndexJob) -> None:
            await run_index_job(job, project_root=project_root, rag=rag)

        try:
            job = tracker.start_job(project_id=project.id, worker=_worker)
        except AlreadyIndexingError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        return IndexJobResponse(job_id=job.id, project_id=job.project_id, status=job.status)

    @router.get(
        "/projects/{project_id}/index/status/{job_id}",
        response_model=IndexStatusResponse,
        tags=["balu_code"],
    )
    async def index_job_status(
        project_id: int,
        job_id: str,
        _user: UserPublic = Depends(get_current_user),
        tracker: IndexJobTracker = Depends(get_index_job_tracker),
    ) -> IndexStatusResponse:
        job = tracker.get_job(job_id)
        if job is None or job.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"indexing job {job_id} not found for project {project_id}",
            )
        return IndexStatusResponse(
            job_id=job.id,
            project_id=job.project_id,
            status=job.status,
            files_total=job.files_total,
            files_processed=job.files_processed,
            chunks_total=job.chunks_total,
            error=job.error,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )

    @router.websocket("/chat")
    async def chat_socket(
        websocket: WebSocket,
        project_id: int,
        store: ProjectStore = Depends(get_project_store),
        ollama: OllamaClient = Depends(get_ollama_client),
        rag_registry: RagRegistry = Depends(get_rag_registry),
        tool_registry: ToolRegistry = Depends(get_tool_registry),
        config: BaluCodePluginConfig = Depends(get_plugin_config),
        audit_log=Depends(get_audit_log),
    ) -> None:
        try:
            user = await _ws_auth(websocket)
        except WebSocketDisconnect:
            return

        try:
            project = await asyncio.to_thread(store.get_project, project_id)
        except ProjectNotFoundError:
            await websocket.close(code=1008, reason="project not found")
            return

        try:
            rag = await rag_registry.get(project.id)
        except Exception as exc:
            await websocket.close(code=1011, reason=f"rag init failed: {exc}")
            return

        repo_map = RepoMap(
            project_root=Path(project.root_path),
            store=store,
            project_id=project.id,
        )

        await websocket.accept()

        deps = TurnDeps(
            ollama=ollama,
            tool_registry=tool_registry,
            project=project,
            repo_map=repo_map,
            rag=rag,
            config=config,
            audit_log=audit_log,
        )
        history: list[dict] = []

        async def _emit(event) -> None:
            await websocket.send_json(event.model_dump())

        _turn_task: asyncio.Task | None = None
        _turn_ctx: TurnContext | None = None

        try:
            while True:
                raw = await websocket.receive_json()
                try:
                    frame = parse_frame(raw)
                except ValidationError as exc:
                    await _emit(Error(code="bad_frame", message=str(exc)[:200]))
                    continue

                if isinstance(frame, UserMessage):
                    if _turn_task is not None and not _turn_task.done():
                        await _emit(
                            Error(code="turn_in_flight", message="a turn is already running")
                        )
                        continue
                    ctx = TurnContext(
                        turn_id=f"t_{uuid.uuid4().hex[:12]}",
                        cancel_token=CancelToken(),
                        pending_approvals={},
                        username=user.username,
                    )
                    _turn_ctx = ctx
                    _turn_task = asyncio.create_task(
                        run_turn(frame.content, history, deps, _emit, ctx)
                    )
                    continue

                if isinstance(frame, Approval):
                    fut = (
                        _turn_ctx.pending_approvals.pop(frame.tool_call_id, None)
                        if _turn_ctx is not None
                        else None
                    )
                    if fut is None:
                        await _emit(
                            Error(
                                code="unknown_approval",
                                message=f"no pending request for {frame.tool_call_id}",
                            )
                        )
                    elif not fut.done():
                        fut.set_result(frame)
                    continue

                if isinstance(frame, Cancel):
                    if _turn_ctx is None or frame.turn_id != _turn_ctx.turn_id:
                        await _emit(
                            Error(code="no_turn_to_cancel", message="no matching turn in flight")
                        )
                        continue
                    _turn_ctx.cancel_token.cancel()
                    for fut in list(_turn_ctx.pending_approvals.values()):
                        if not fut.done():
                            fut.cancel()
                    continue

                await _emit(
                    Error(
                        code="unsupported_frame",
                        message=f"frame type '{frame.type}' is not supported",
                    )
                )
        except WebSocketDisconnect:
            if _turn_task is not None and not _turn_task.done():
                _turn_task.cancel()
            return

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

        result = await client.prompt(
            session_id,
            text=last_user.content,
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

    return router


__all__ = ["build_router"]
