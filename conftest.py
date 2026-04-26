"""Repo-root pytest bootstrap.

Runs before any test module or plugin package is imported. Adds the
BaluHost stub to sys.path so ``from app.plugins.base import ...`` inside
``plugin/__init__.py`` resolves during collection, without BaluHost
needing to be installed. Also adds shared/src and cli/src.
"""

from __future__ import annotations

import sys
from pathlib import Path

_STUB_DIR = Path(__file__).parent / "plugin" / "tests" / "fixtures" / "baluhost_stub"
if str(_STUB_DIR) not in sys.path:
    sys.path.insert(0, str(_STUB_DIR))

_SHARED_SRC = Path(__file__).parent / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

_CLI_SRC = Path(__file__).parent / "cli" / "src"
if str(_CLI_SRC) not in sys.path:
    sys.path.insert(0, str(_CLI_SRC))
