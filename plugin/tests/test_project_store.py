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


def test_upsert_inserts_new_repo_map_entry(store):
    p = store.create_project(name="rm1", root_path="/x", config_yaml=None)
    store.upsert_repo_map_entry(
        project_id=p.id,
        file_path="src/a.py",
        mtime=1700000000.0,
        sha1="aaa",
        symbols_json='{"imports": []}',
    )
    rows = store.list_repo_map_entries(p.id)
    assert len(rows) == 1
    assert rows[0].file_path == "src/a.py"
    assert rows[0].sha1 == "aaa"
    assert rows[0].symbols_json == '{"imports": []}'


def test_upsert_replaces_existing_entry(store):
    p = store.create_project(name="rm2", root_path="/x", config_yaml=None)
    store.upsert_repo_map_entry(p.id, "a.py", 1.0, "sha1_old", '{"v":1}')
    store.upsert_repo_map_entry(p.id, "a.py", 2.0, "sha1_new", '{"v":2}')
    rows = store.list_repo_map_entries(p.id)
    assert len(rows) == 1
    assert rows[0].mtime == 2.0
    assert rows[0].sha1 == "sha1_new"
    assert rows[0].symbols_json == '{"v":2}'


def test_list_repo_map_entries_isolates_by_project(store):
    p1 = store.create_project(name="rm3a", root_path="/x", config_yaml=None)
    p2 = store.create_project(name="rm3b", root_path="/y", config_yaml=None)
    store.upsert_repo_map_entry(p1.id, "p1.py", 1.0, "h1", "{}")
    store.upsert_repo_map_entry(p2.id, "p2.py", 1.0, "h2", "{}")
    rows1 = store.list_repo_map_entries(p1.id)
    rows2 = store.list_repo_map_entries(p2.id)
    assert [r.file_path for r in rows1] == ["p1.py"]
    assert [r.file_path for r in rows2] == ["p2.py"]


def test_delete_repo_map_entries_drops_paths_not_in_keep_set(store):
    p = store.create_project(name="rm4", root_path="/x", config_yaml=None)
    for path in ("keep.py", "drop.py", "also_drop.py"):
        store.upsert_repo_map_entry(p.id, path, 1.0, "h", "{}")
    store.delete_repo_map_entries(p.id, paths_to_keep={"keep.py"})
    remaining = {r.file_path for r in store.list_repo_map_entries(p.id)}
    assert remaining == {"keep.py"}


def test_delete_repo_map_entries_with_empty_keep_set_clears_all(store):
    p = store.create_project(name="rm5", root_path="/x", config_yaml=None)
    store.upsert_repo_map_entry(p.id, "a.py", 1.0, "h", "{}")
    store.delete_repo_map_entries(p.id, paths_to_keep=set())
    assert store.list_repo_map_entries(p.id) == []


def test_deleting_project_cascades_to_repo_map_cache(store):
    p = store.create_project(name="rm6", root_path="/x", config_yaml=None)
    store.upsert_repo_map_entry(p.id, "a.py", 1.0, "h", "{}")
    store.delete_project(p.id)
    # Re-create with the same name — the new project gets a fresh id;
    # the old rows must have cascaded away rather than lingering on the
    # detached project_id.
    p2 = store.create_project(name="rm6", root_path="/x", config_yaml=None)
    assert store.list_repo_map_entries(p2.id) == []
