"""Pytest bootstrap for plugin tests.

Inserts the BaluHost stub onto sys.path so that ``from app.plugins.base ...``
resolves to a local fixture rather than requiring BaluHost to be installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_STUB_DIR = Path(__file__).parent / "fixtures" / "baluhost_stub"
sys.path.insert(0, str(_STUB_DIR))

# Sanity: the stub must import cleanly before any test collection runs.
from app.plugins.base import PluginBase, PluginMetadata  # noqa: E402,F401

from plugin.deps import clear_singletons  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_plugin_singletons():
    """Clear the plugin/deps.py module-level singletons before and after each test.

    Applies to every test under ``plugin/tests/`` so route tests in Tasks
    10-13 can rely on a clean slate without duplicating the fixture.
    """
    clear_singletons()
    yield
    clear_singletons()
