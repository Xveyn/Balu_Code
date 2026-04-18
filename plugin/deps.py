"""Module-level singletons for the balu_code plugin.

``BaluCodePlugin.on_startup`` constructs the ProjectStore and OllamaClient
and registers them here via ``set_singletons``. Route handlers depend on
the ``get_*`` accessors so tests can override them with
``app.dependency_overrides``.
"""

from __future__ import annotations

from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore

_store: ProjectStore | None = None
_ollama: OllamaClient | None = None


def set_singletons(store: ProjectStore, ollama: OllamaClient) -> None:
    global _store, _ollama
    _store = store
    _ollama = ollama


def clear_singletons() -> None:
    global _store, _ollama
    _store = None
    _ollama = None


def get_project_store() -> ProjectStore:
    if _store is None:
        raise RuntimeError("balu_code plugin not initialized (ProjectStore missing)")
    return _store


def get_ollama_client() -> OllamaClient:
    if _ollama is None:
        raise RuntimeError("balu_code plugin not initialized (OllamaClient missing)")
    return _ollama


__all__ = [
    "clear_singletons",
    "get_ollama_client",
    "get_project_store",
    "set_singletons",
]
