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
    assert result["provider"]["ollama"]["options"]["baseURL"] == "http://10.0.0.5:11434"
    assert "permission" not in result or result["permission"] == {}


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
