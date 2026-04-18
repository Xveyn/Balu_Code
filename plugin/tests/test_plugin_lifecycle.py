"""Tests for BaluCodePlugin lifecycle + config hooks."""
from __future__ import annotations

import pytest

from plugin import BaluCodePlugin
from plugin.config import BaluCodePluginConfig
from plugin.deps import (
    clear_singletons,
    get_ollama_client,
    get_project_store,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    clear_singletons()
    yield
    clear_singletons()


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
