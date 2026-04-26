"""XDG-aware path constants for ~/.config/balu-code/."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME") or None
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "balu-code"


def config_yaml() -> Path:
    return config_dir() / "config.yaml"


def credentials_yaml() -> Path:
    return config_dir() / "credentials.yaml"


def permissions_yaml() -> Path:
    return config_dir() / "permissions.yaml"


def sessions_dir(server_url: str, project_id: int) -> Path:
    key = f"{server_url}:{project_id}".encode()
    h = hashlib.sha1(key, usedforsecurity=False).hexdigest()[:16]
    xdg = os.environ.get("XDG_DATA_HOME") or None
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "balu-code" / "sessions" / h


__all__ = ["config_dir", "config_yaml", "credentials_yaml", "permissions_yaml", "sessions_dir"]
