"""Module-level singletons for the balu_code plugin.

``BaluCodePlugin.on_startup`` constructs the ProjectStore, OllamaClient,
RagRegistry, and IndexJobTracker and registers them here via
``set_singletons``. Route handlers depend on the ``get_*`` accessors so
tests can override them with ``app.dependency_overrides``.
"""

from __future__ import annotations

from plugin.services.index_jobs import IndexJobTracker
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore
from plugin.services.rag_registry import RagRegistry

_store: ProjectStore | None = None
_ollama: OllamaClient | None = None
_rag_registry: RagRegistry | None = None
_index_job_tracker: IndexJobTracker | None = None


def set_singletons(
    store: ProjectStore,
    ollama: OllamaClient,
    rag_registry: RagRegistry,
    index_job_tracker: IndexJobTracker,
) -> None:
    global _store, _ollama, _rag_registry, _index_job_tracker
    _store = store
    _ollama = ollama
    _rag_registry = rag_registry
    _index_job_tracker = index_job_tracker


def clear_singletons() -> None:
    global _store, _ollama, _rag_registry, _index_job_tracker
    _store = None
    _ollama = None
    _rag_registry = None
    _index_job_tracker = None


def get_project_store() -> ProjectStore:
    if _store is None:
        raise RuntimeError("balu_code plugin not initialized (ProjectStore missing)")
    return _store


def get_ollama_client() -> OllamaClient:
    if _ollama is None:
        raise RuntimeError("balu_code plugin not initialized (OllamaClient missing)")
    return _ollama


def get_rag_registry() -> RagRegistry:
    if _rag_registry is None:
        raise RuntimeError("balu_code plugin not initialized (RagRegistry missing)")
    return _rag_registry


def get_index_job_tracker() -> IndexJobTracker:
    if _index_job_tracker is None:
        raise RuntimeError("balu_code plugin not initialized (IndexJobTracker missing)")
    return _index_job_tracker


__all__ = [
    "clear_singletons",
    "get_index_job_tracker",
    "get_ollama_client",
    "get_project_store",
    "get_rag_registry",
    "set_singletons",
]
