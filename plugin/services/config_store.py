"""Persist and load BaluCodePluginConfig as JSON in the plugin data dir."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import BaluCodePluginConfig

_CONFIG_FILE = "plugin_config.json"


def load_plugin_config(data_dir: Path) -> BaluCodePluginConfig:
    path = data_dir / _CONFIG_FILE
    if not path.exists():
        return BaluCodePluginConfig()
    return BaluCodePluginConfig.model_validate(json.loads(path.read_text()))


def save_plugin_config(config: BaluCodePluginConfig, data_dir: Path) -> None:
    (data_dir / _CONFIG_FILE).write_text(config.model_dump_json())


__all__ = ["load_plugin_config", "save_plugin_config"]
