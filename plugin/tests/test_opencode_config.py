"""Tests for opencode.json config mapping."""

from __future__ import annotations

import json

from plugin.config import BaluCodePluginConfig
from plugin.services.opencode_config import to_opencode_config, write_opencode_config


def test_maps_ollama_url_and_default_model():
    cfg = BaluCodePluginConfig(
        ollama_base_url="http://10.0.0.5:11434",
        chat_model="qwen2.5-coder:32b",
    )
    result = to_opencode_config(cfg, file_write_allowed=True)
    assert result["model"] == "ollama/qwen2.5-coder:32b"
    # opencode's ollama-ai-provider-v2 expects baseURL ending in /api
    assert result["provider"]["ollama"]["options"]["baseURL"] == "http://10.0.0.5:11434/api"
    assert result["provider"]["ollama"]["npm"] == "ollama-ai-provider-v2"
    assert "qwen2.5-coder:32b" in result["provider"]["ollama"]["models"]
    assert "permission" not in result or result["permission"] == {}


def test_url_with_trailing_slash_or_api_is_normalized():
    cfg = BaluCodePluginConfig(ollama_base_url="http://x:1/api/")
    result = to_opencode_config(cfg, file_write_allowed=True)
    assert result["provider"]["ollama"]["options"]["baseURL"] == "http://x:1/api"


def test_model_num_ctx_matches_plugin_context_window():
    """Avoid silent 4096-token truncation by forwarding context_window as num_ctx."""
    cfg = BaluCodePluginConfig(chat_model="x:1b", context_window=16384)
    result = to_opencode_config(cfg, file_write_allowed=True)
    assert result["provider"]["ollama"]["models"]["x:1b"]["options"]["num_ctx"] == 16384


def test_readonly_locks_down_edit_and_bash_when_write_denied():
    cfg = BaluCodePluginConfig()
    result = to_opencode_config(cfg, file_write_allowed=False)
    assert result["permission"]["edit"] == "deny"
    assert result["permission"]["bash"] == "deny"


def test_write_opencode_config_writes_file(tmp_path):
    cfg = BaluCodePluginConfig()
    path = write_opencode_config(tmp_path, cfg, file_write_allowed=True)
    assert path == tmp_path / "opencode.json"
    payload = json.loads(path.read_text())
    assert "provider" in payload
    assert "model" in payload


def test_write_opencode_config_creates_parent(tmp_path):
    cfg = BaluCodePluginConfig()
    nested = tmp_path / "sub" / "dir"
    path = write_opencode_config(nested, cfg, file_write_allowed=True)
    assert path.exists()
