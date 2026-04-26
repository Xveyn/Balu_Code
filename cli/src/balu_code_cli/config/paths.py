"""XDG-aware path constants for ~/.config/balu-code/."""

from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "balu-code"


def config_yaml() -> Path:
    return config_dir() / "config.yaml"


def credentials_yaml() -> Path:
    return config_dir() / "credentials.yaml"


def permissions_yaml() -> Path:
    return config_dir() / "permissions.yaml"


__all__ = ["config_dir", "config_yaml", "credentials_yaml", "permissions_yaml"]
