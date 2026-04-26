"""Tests for BaluCodePlugin lifecycle + config hooks."""

from __future__ import annotations

import pytest

from plugin import BaluCodePlugin
from plugin.config import BaluCodePluginConfig
from plugin.deps import (
    get_ollama_client,
    get_project_store,
)


def test_get_config_schema_returns_pydantic_model():
    p = BaluCodePlugin()
    assert p.get_config_schema() is BaluCodePluginConfig


def test_get_default_config_matches_defaults():
    p = BaluCodePlugin()
    defaults = p.get_default_config()
    expected = BaluCodePluginConfig().model_dump()
    assert defaults == expected


def test_deps_raise_before_startup():
    with pytest.raises(RuntimeError):
        get_project_store()
    with pytest.raises(RuntimeError):
        get_ollama_client()


@pytest.mark.asyncio
async def test_startup_registers_singletons(tmp_path, monkeypatch):
    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    p = BaluCodePlugin()
    await p.on_startup()
    try:
        store = get_project_store()
        ollama = get_ollama_client()
        assert store.list_projects() == []
        assert (tmp_path / "store.db").exists()
        assert ollama._base_url == "http://127.0.0.1:11434"
    finally:
        await p.on_shutdown()


@pytest.mark.asyncio
async def test_shutdown_clears_singletons(tmp_path, monkeypatch):
    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    p = BaluCodePlugin()
    await p.on_startup()
    await p.on_shutdown()
    with pytest.raises(RuntimeError):
        get_project_store()
    with pytest.raises(RuntimeError):
        get_ollama_client()


@pytest.mark.asyncio
async def test_startup_registers_rag_registry_and_tracker(tmp_path, monkeypatch):
    from plugin.deps import (
        clear_singletons,
        get_index_job_tracker,
        get_rag_registry,
    )
    from plugin.services.index_jobs import IndexJobTracker
    from plugin.services.rag_registry import RagRegistry

    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    clear_singletons()
    p = BaluCodePlugin()
    await p.on_startup()
    try:
        registry = get_rag_registry()
        tracker = get_index_job_tracker()
        assert isinstance(registry, RagRegistry)
        assert isinstance(tracker, IndexJobTracker)
    finally:
        await p.on_shutdown()


@pytest.mark.asyncio
async def test_shutdown_clears_rag_registry_and_tracker(tmp_path, monkeypatch):
    from plugin.deps import (
        clear_singletons,
        get_index_job_tracker,
        get_rag_registry,
    )

    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    clear_singletons()
    p = BaluCodePlugin()
    await p.on_startup()
    await p.on_shutdown()
    with pytest.raises(RuntimeError):
        get_rag_registry()
    with pytest.raises(RuntimeError):
        get_index_job_tracker()


@pytest.mark.asyncio
async def test_startup_registers_tool_registry_and_config(tmp_path, monkeypatch):
    from plugin.deps import (
        clear_singletons,
        get_plugin_config,
        get_tool_registry,
    )
    from plugin.services.tools import ToolRegistry

    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    clear_singletons()
    p = BaluCodePlugin()
    await p.on_startup()
    try:
        reg = get_tool_registry()
        cfg = get_plugin_config()
        assert isinstance(reg, ToolRegistry)
        assert reg.names() == ["glob", "grep", "read_file"]
        assert isinstance(cfg, BaluCodePluginConfig)
    finally:
        await p.on_shutdown()


@pytest.mark.asyncio
async def test_shutdown_clears_tool_registry_and_config(tmp_path, monkeypatch):
    from plugin.deps import (
        clear_singletons,
        get_plugin_config,
        get_tool_registry,
    )

    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    clear_singletons()
    p = BaluCodePlugin()
    await p.on_startup()
    await p.on_shutdown()
    with pytest.raises(RuntimeError):
        get_tool_registry()
    with pytest.raises(RuntimeError):
        get_plugin_config()


@pytest.mark.asyncio
async def test_startup_registers_audit_log(tmp_path, monkeypatch):
    from plugin.deps import clear_singletons, get_audit_log
    from plugin.services.audit import AuditLogger

    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    clear_singletons()
    p = BaluCodePlugin()
    await p.on_startup()
    try:
        al = get_audit_log()
        assert isinstance(al, AuditLogger)
    finally:
        await p.on_shutdown()


@pytest.mark.asyncio
async def test_shutdown_clears_audit_log(tmp_path, monkeypatch):
    from plugin.deps import clear_singletons, get_audit_log

    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    clear_singletons()
    p = BaluCodePlugin()
    await p.on_startup()
    await p.on_shutdown()
    with pytest.raises(RuntimeError):
        get_audit_log()
