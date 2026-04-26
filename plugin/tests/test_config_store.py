from __future__ import annotations

import json

from plugin.config import BaluCodePluginConfig
from plugin.services.config_store import load_plugin_config, save_plugin_config


def test_load_returns_defaults_when_file_missing(tmp_path):
    cfg = load_plugin_config(tmp_path)
    assert cfg == BaluCodePluginConfig()


def test_save_then_load_round_trips(tmp_path):
    original = BaluCodePluginConfig(chat_model="qwen2.5-coder:7b", temperature=0.5)
    save_plugin_config(original, tmp_path)
    loaded = load_plugin_config(tmp_path)
    assert loaded == original


def test_save_writes_valid_json(tmp_path):
    save_plugin_config(BaluCodePluginConfig(), tmp_path)
    data = json.loads((tmp_path / "plugin_config.json").read_text())
    assert data["chat_model"] == "qwen2.5-coder:14b-instruct-q4_K_M"
