"""Tests for config/permissions.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from balu_code_cli.config.permissions import (
    PermissionsStore,
    load_permissions,
    save_permissions,
)

SERVER = "https://balu.example.com"
PID = 42


def test_lookup_returns_none_when_no_entry():
    store = PermissionsStore()
    assert store.lookup(SERVER, PID, "write_file") is None


def test_set_and_lookup_round_trips():
    store = PermissionsStore()
    store.set(SERVER, PID, "write_file", True)
    assert store.lookup(SERVER, PID, "write_file") is True


def test_set_false_and_lookup():
    store = PermissionsStore()
    store.set(SERVER, PID, "run_bash", False)
    assert store.lookup(SERVER, PID, "run_bash") is False


def test_lookup_missing_tool_returns_none():
    store = PermissionsStore()
    store.set(SERVER, PID, "write_file", True)
    assert store.lookup(SERVER, PID, "run_bash") is None


def test_load_returns_empty_when_file_missing(tmp_path):
    store = load_permissions(tmp_path / "permissions.yaml")
    assert store.permissions == {}


def test_save_and_load_round_trips(tmp_path):
    path = tmp_path / "permissions.yaml"
    store = PermissionsStore()
    store.set(SERVER, PID, "write_file", True)
    save_permissions(store, path)
    loaded = load_permissions(path)
    assert loaded.lookup(SERVER, PID, "write_file") is True


def test_load_corrupt_yaml_returns_empty(tmp_path):
    path = tmp_path / "permissions.yaml"
    path.write_text("{{{{invalid yaml")
    store = load_permissions(path)
    assert store.permissions == {}
