"""Module-level singletons for the balu_code plugin."""

from __future__ import annotations

from pathlib import Path

from .config import BaluCodePluginConfig
from .services.audit import AuditLogger
from .services.ollama_client import OllamaClient
from .services.opencode_client import OpencodeClient
from .services.opencode_runtime import ServerHandle
from .services.project_store import ProjectStore

_store: ProjectStore | None = None
_ollama: OllamaClient | None = None
_plugin_config: BaluCodePluginConfig | None = None
_audit_log: AuditLogger | None = None
_data_dir: Path | None = None
_opencode_handle: ServerHandle | None = None
_opencode_client: OpencodeClient | None = None


def set_singletons(
    store: ProjectStore,
    ollama: OllamaClient,
    plugin_config: BaluCodePluginConfig,
    audit_log: AuditLogger,
    data_dir: Path,
) -> None:
    global _store, _ollama, _plugin_config, _audit_log, _data_dir
    _store = store
    _ollama = ollama
    _plugin_config = plugin_config
    _audit_log = audit_log
    _data_dir = data_dir


def clear_singletons() -> None:
    global _store, _ollama, _plugin_config, _audit_log, _data_dir
    global _opencode_handle, _opencode_client
    _store = None
    _ollama = None
    _plugin_config = None
    _audit_log = None
    _data_dir = None
    _opencode_handle = None
    _opencode_client = None


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


def set_opencode(handle: ServerHandle, client: OpencodeClient) -> None:
    global _opencode_handle, _opencode_client
    _opencode_handle = handle
    _opencode_client = client


def clear_opencode() -> None:
    global _opencode_handle, _opencode_client
    _opencode_handle = None
    _opencode_client = None


def get_opencode_handle() -> ServerHandle:
    if _opencode_handle is None:
        raise RuntimeError("opencode runtime not initialized")
    return _opencode_handle


def get_opencode_client() -> OpencodeClient:
    if _opencode_client is None:
        raise RuntimeError("opencode client not initialized")
    return _opencode_client


__all__ = [
    "clear_opencode",
    "clear_singletons",
    "get_audit_log",
    "get_data_dir",
    "get_ollama_client",
    "get_opencode_client",
    "get_opencode_handle",
    "get_plugin_config",
    "get_project_store",
    "set_opencode",
    "set_singletons",
    "update_plugin_config",
]
