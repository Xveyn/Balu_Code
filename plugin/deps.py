"""Module-level singletons for the balu_code plugin."""

from __future__ import annotations

from pathlib import Path

from plugin.config import BaluCodePluginConfig
from plugin.services.audit import AuditLogger
from plugin.services.index_jobs import IndexJobTracker
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore
from plugin.services.rag_registry import RagRegistry
from plugin.services.tools import ToolRegistry

_store: ProjectStore | None = None
_ollama: OllamaClient | None = None
_rag_registry: RagRegistry | None = None
_index_job_tracker: IndexJobTracker | None = None
_tool_registry: ToolRegistry | None = None
_plugin_config: BaluCodePluginConfig | None = None
_audit_log: AuditLogger | None = None
_data_dir: Path | None = None


def set_singletons(
    store: ProjectStore,
    ollama: OllamaClient,
    rag_registry: RagRegistry,
    index_job_tracker: IndexJobTracker,
    tool_registry: ToolRegistry,
    plugin_config: BaluCodePluginConfig,
    audit_log: AuditLogger,
    data_dir: Path,
) -> None:
    global _store, _ollama, _rag_registry, _index_job_tracker, _tool_registry
    global _plugin_config, _audit_log, _data_dir
    _store = store
    _ollama = ollama
    _rag_registry = rag_registry
    _index_job_tracker = index_job_tracker
    _tool_registry = tool_registry
    _plugin_config = plugin_config
    _audit_log = audit_log
    _data_dir = data_dir


def clear_singletons() -> None:
    global _store, _ollama, _rag_registry, _index_job_tracker, _tool_registry
    global _plugin_config, _audit_log, _data_dir
    _store = None
    _ollama = None
    _rag_registry = None
    _index_job_tracker = None
    _tool_registry = None
    _plugin_config = None
    _audit_log = None
    _data_dir = None


def update_plugin_config(config: BaluCodePluginConfig) -> None:
    global _plugin_config
    _plugin_config = config


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


def get_tool_registry() -> ToolRegistry:
    if _tool_registry is None:
        raise RuntimeError("balu_code plugin not initialized (ToolRegistry missing)")
    return _tool_registry


def get_plugin_config() -> BaluCodePluginConfig:
    if _plugin_config is None:
        raise RuntimeError("balu_code plugin not initialized (BaluCodePluginConfig missing)")
    return _plugin_config


def get_audit_log() -> AuditLogger:
    if _audit_log is None:
        raise RuntimeError("balu_code plugin not initialized (AuditLogger missing)")
    return _audit_log


def get_data_dir() -> Path:
    if _data_dir is None:
        raise RuntimeError("balu_code plugin not initialized (data_dir missing)")
    return _data_dir


__all__ = [
    "clear_singletons",
    "get_audit_log",
    "get_data_dir",
    "get_index_job_tracker",
    "get_ollama_client",
    "get_plugin_config",
    "get_project_store",
    "get_rag_registry",
    "get_tool_registry",
    "set_singletons",
    "update_plugin_config",
]
