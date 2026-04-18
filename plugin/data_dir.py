"""Resolve and create the balu_code plugin's data directory.

Order of precedence:
1. ``$BALU_CODE_DATA_DIR`` (ops/CI override) — only if non-empty.
2. ``~/.local/share/balu-code/`` (XDG-style default).

The directory is always created (``mkdir(parents=True, exist_ok=True)``)
so callers can assume it exists.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_data_dir() -> Path:
    override = os.environ.get("BALU_CODE_DATA_DIR", "").strip()
    if override:
        target = Path(override).expanduser()
    else:
        target = Path.home() / ".local" / "share" / "balu-code"
    target.mkdir(parents=True, exist_ok=True)
    return target


__all__ = ["resolve_data_dir"]
