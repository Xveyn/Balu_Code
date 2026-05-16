"""Request/response Pydantic schemas for balu_code routes.

Kept separate from ``plugin/__init__.py`` so the plugin entry module
stays small and so route handlers in ``plugin/routes.py`` can import
schemas without pulling in lifecycle code.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .services.ollama_client import OllamaModel
from .services.project_store import Project


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    root_path: str = Field(..., min_length=1)
    config_yaml: str | None = None


class ProjectsResponse(BaseModel):
    projects: list[Project]


class ModelsResponse(BaseModel):
    models: list[OllamaModel]


class ConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ollama_base_url: str | None = None
    chat_model: str | None = None
    embed_model: str | None = None
    context_window: int | None = None
    repo_map_enabled: bool | None = None
    repo_map_budget: int | None = None
    rag_budget: int | None = None
    rag_top_k: int | None = None
    max_iterations: int | None = None
    max_total_tokens_per_turn: int | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    poll_interval_seconds: int | None = Field(default=None, ge=3, le=300)


class LogEntry(BaseModel):
    id: int
    timestamp: str
    user: str | None
    action: str
    resource: str | None
    success: bool
    error_message: str | None = None
    turn_id: str | None = None
    tool_call_id: str | None = None


class LogsResponse(BaseModel):
    entries: list[LogEntry]


class LoadedModel(BaseModel):
    name: str
    size_vram: int
    context_length: int | None = None


class OllamaSystemInfo(BaseModel):
    reachable: bool
    loaded_models: list[LoadedModel] = []


class GpuInfo(BaseModel):
    available: bool
    backend: str | None = None
    utilization_pct: int | None = None
    vram_used_bytes: int | None = None
    vram_total_bytes: int | None = None


class SystemResponse(BaseModel):
    ollama: OllamaSystemInfo
    gpu: GpuInfo


class DayStat(BaseModel):
    date: str
    requests: int
    tokens_in: int
    tokens_out: int


class ModelStat(BaseModel):
    model: str
    requests: int
    avg_tokens_per_s: float


class ToolStat(BaseModel):
    tool: str
    calls: int
    success_rate: float


class ApprovalSummary(BaseModel):
    auto_approved: int
    user_approved: int
    rejected: int


class StatsResponse(BaseModel):
    last_n_days: list[DayStat]
    by_model: list[ModelStat]
    top_tools: list[ToolStat]
    approval_summary: ApprovalSummary


class ChatV2Message(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatV2Request(BaseModel):
    messages: list[ChatV2Message]
    model: str | None = None  # "provider/modelID"; falls back to plugin default


class RuntimeStatusResponse(BaseModel):
    healthy: bool
    port: int
    pid: int
    binary_version: str


class RuntimeCredentialsResponse(BaseModel):
    """Basic-Auth credentials for the embedded OpenCode server.

    Returned for callers who need to attach to the local server with the
    standalone ``opencode`` CLI or a browser:
        OPENCODE_SERVER_PASSWORD=<password> opencode attach http://127.0.0.1:<port>
    """

    username: str
    password: str


__all__ = [
    "ApprovalSummary",
    "ChatV2Message",
    "ChatV2Request",
    "ConfigUpdateRequest",
    "DayStat",
    "GpuInfo",
    "LoadedModel",
    "LogEntry",
    "LogsResponse",
    "ModelStat",
    "ModelsResponse",
    "OllamaSystemInfo",
    "ProjectCreate",
    "ProjectsResponse",
    "RuntimeCredentialsResponse",
    "RuntimeStatusResponse",
    "StatsResponse",
    "SystemResponse",
    "ToolStat",
]
