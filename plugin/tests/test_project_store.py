"""Tests for ProjectStore."""
from __future__ import annotations

import pytest

from plugin.services.project_store import (
    DuplicateProjectError,
    Project,
    ProjectNotFoundError,
    ProjectStore,
)


@pytest.fixture
def store(tmp_path):
    s = ProjectStore(tmp_path / "store.db")
    yield s
    s.close()


def test_init_schema_is_idempotent(tmp_path):
    s1 = ProjectStore(tmp_path / "store.db")
    s1.close()
    # Re-open same file: must not raise, must preserve data.
    s2 = ProjectStore(tmp_path / "store.db")
    assert s2.list_projects() == []
    s2.close()


def test_create_and_get_project(store):
    p = store.create_project(name="baluhost", root_path="/home/sven/code/bh", config_yaml=None)
    assert isinstance(p, Project)
    assert p.id > 0
    assert p.name == "baluhost"
    assert p.root_path == "/home/sven/code/bh"
    assert p.config_yaml is None
    assert p.created_at == p.updated_at
    fetched = store.get_project(p.id)
    assert fetched == p


def test_create_project_with_config_yaml(store):
    yaml_blob = "project:\n  name: x\n"
    p = store.create_project(name="x", root_path="/tmp/x", config_yaml=yaml_blob)
    assert p.config_yaml == yaml_blob


def test_list_projects_returns_all(store):
    a = store.create_project(name="a", root_path="/a", config_yaml=None)
    b = store.create_project(name="b", root_path="/b", config_yaml=None)
    result = store.list_projects()
    ids = [p.id for p in result]
    assert a.id in ids
    assert b.id in ids
    assert len(result) == 2


def test_duplicate_name_raises(store):
    store.create_project(name="dup", root_path="/a", config_yaml=None)
    with pytest.raises(DuplicateProjectError):
        store.create_project(name="dup", root_path="/b", config_yaml=None)


def test_get_missing_project_raises(store):
    with pytest.raises(ProjectNotFoundError):
        store.get_project(9999)


def test_delete_removes_project(store):
    p = store.create_project(name="todelete", root_path="/x", config_yaml=None)
    store.delete_project(p.id)
    with pytest.raises(ProjectNotFoundError):
        store.get_project(p.id)
    assert store.list_projects() == []


def test_delete_missing_raises(store):
    with pytest.raises(ProjectNotFoundError):
        store.delete_project(9999)


def test_repo_map_cache_table_exists(store):
    # Phase 2 creates the table but does not populate it.
    conn = store._conn  # internal, but test covers schema contract
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='repo_map_cache'"
    ).fetchone()
    assert row is not None
