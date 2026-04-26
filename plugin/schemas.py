"""Request/response Pydantic schemas for balu_code routes.

Kept separate from ``plugin/__init__.py`` so the plugin entry module
stays small and so route handlers in ``plugin/routes.py`` can import
schemas without pulling in lifecycle code.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .services.index_jobs import JobStatus
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


class RepoMapResponse(BaseModel):
    text: str
    file_count: int = Field(..., ge=0)
    truncated_files: list[str] = Field(default_factory=list)
    total_bytes: int = Field(..., ge=0)


class IndexJobResponse(BaseModel):
    job_id: str
    project_id: int
    status: JobStatus


class IndexStatusResponse(BaseModel):
    job_id: str
    project_id: int
    status: JobStatus
    files_total: int
    files_processed: int
    chunks_total: int  # chunks upserted in this run, not total chunks in the index
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ollama_base_url: str | None = None
    chat_model: str | None = None
    embed_model: str | None = None
    context_window: int | None = None
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


__all__ = [
    "ConfigUpdateRequest",
    "GpuInfo",
    "IndexJobResponse",
    "IndexStatusResponse",
    "LoadedModel",
    "LogEntry",
    "LogsResponse",
    "ModelsResponse",
    "OllamaSystemInfo",
    "ProjectCreate",
    "ProjectsResponse",
    "RepoMapResponse",
    "SystemResponse",
]
