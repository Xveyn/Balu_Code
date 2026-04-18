"""Tests for resolve_data_dir()."""
from __future__ import annotations

from pathlib import Path

from plugin.data_dir import resolve_data_dir


def test_env_var_takes_precedence(tmp_path, monkeypatch):
    target = tmp_path / "balu-code-data"
    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(target))
    result = resolve_data_dir()
    assert result == target
    assert result.is_dir()


def test_fallback_to_xdg_home(tmp_path, monkeypatch):
    monkeypatch.delenv("BALU_CODE_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = resolve_data_dir()
    assert result == tmp_path / ".local" / "share" / "balu-code"
    assert result.is_dir()


def test_idempotent_when_dir_already_exists(tmp_path, monkeypatch):
    target = tmp_path / "existing"
    target.mkdir()
    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(target))
    # Call twice — must not raise, must return same path.
    first = resolve_data_dir()
    second = resolve_data_dir()
    assert first == second == target


def test_creates_nested_missing_dirs(tmp_path, monkeypatch):
    target = tmp_path / "a" / "b" / "c"
    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(target))
    result = resolve_data_dir()
    assert result.is_dir()
    assert result == target


def test_empty_env_var_uses_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("BALU_CODE_DATA_DIR", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    result = resolve_data_dir()
    assert result == tmp_path / ".local" / "share" / "balu-code"
