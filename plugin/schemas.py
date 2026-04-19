"""Request/response Pydantic schemas for balu_code routes.

Kept separate from ``plugin/__init__.py`` so the plugin entry module
stays small and so route handlers in ``plugin/routes.py`` can import
schemas without pulling in lifecycle code.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from plugin.services.index_jobs import JobStatus
from plugin.services.ollama_client import OllamaModel
from plugin.services.project_store import Project


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
    chunks_total: int
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


__all__ = [
    "IndexJobResponse",
    "IndexStatusResponse",
    "ModelsResponse",
    "ProjectCreate",
    "ProjectsResponse",
    "RepoMapResponse",
]
