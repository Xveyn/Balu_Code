"""Tests for config/loader.py and config/paths.py."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_config_dir_uses_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Re-import after env change to pick up new value
    import importlib
    import balu_code_cli.config.paths as paths_mod
    importlib.reload(paths_mod)
    assert paths_mod.config_dir() == tmp_path / "balu-code"


def test_config_dir_defaults_to_home_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib
    import balu_code_cli.config.paths as paths_mod
    importlib.reload(paths_mod)
    assert paths_mod.config_dir() == tmp_path / ".config" / "balu-code"
