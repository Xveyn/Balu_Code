"""Tests for plugin/services/repo_map.py RepoMap.walk_and_cache()."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugin.services.project_store import ProjectStore
from plugin.services.repo_map import (
    FileSymbols,
    ProjectRootNotAccessible,
    RepoMap,
)


@pytest.fixture
def store(tmp_path):
    s = ProjectStore(tmp_path / "store.db")
    yield s
    s.close()


@pytest.fixture
def project(store, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    p = store.create_project("p", str(root), None)
    return p, root


def test_walk_collects_python_files(store, project):
    _, root = project
    (root / "a.py").write_text("def foo(): pass\n")
    (root / "b.py").write_text("class C: pass\n")
    rm = RepoMap(root, store, project_id=project[0].id)
    files = rm.walk_and_cache()
    paths = sorted(f.path for f in files)
    assert paths == ["a.py", "b.py"]


def test_walk_collects_js_and_ts(store, project):
    _, root = project
    (root / "a.ts").write_text("function f() { }\n")
    (root / "b.js").write_text("function g() { }\n")
    (root / "c.tsx").write_text("function H() { return null as any; }\n")
    rm = RepoMap(root, store, project_id=project[0].id)
    files = rm.walk_and_cache()
    paths = sorted(f.path for f in files)
    assert paths == ["a.ts", "b.js", "c.tsx"]


def test_walk_ignores_node_modules(store, project):
    _, root = project
    (root / "a.py").write_text("def foo(): pass\n")
    nm = root / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "ignored.js").write_text("function x() { }\n")
    rm = RepoMap(root, store, project_id=project[0].id)
    files = rm.walk_and_cache()
    assert [f.path for f in files] == ["a.py"]


def test_walk_ignores_hidden_dirs(store, project):
    _, root = project
    (root / "a.py").write_text("def foo(): pass\n")
    (root / ".git").mkdir()
    (root / ".git" / "x.py").write_text("def x(): pass\n")
    rm = RepoMap(root, store, project_id=project[0].id)
    files = rm.walk_and_cache()
    assert [f.path for f in files] == ["a.py"]


def test_walk_populates_cache_first_run(store, project):
    pid = project[0].id
    _, root = project
    (root / "a.py").write_text("def foo(): pass\n")
    rm = RepoMap(root, store, project_id=pid)
    rm.walk_and_cache()
    rows = store.list_repo_map_entries(pid)
    assert len(rows) == 1
    assert rows[0].file_path == "a.py"
    payload = json.loads(rows[0].symbols_json)
    assert payload["v"] == 1
    assert payload["functions"][0]["name"] == "foo"


def test_walk_cache_hit_skips_parser(monkeypatch, store, project):
    pid = project[0].id
    _, root = project
    (root / "a.py").write_text("def foo(): pass\n")
    rm = RepoMap(root, store, project_id=pid)
    rm.walk_and_cache()

    from plugin.services.parsers import python as py_mod

    call_count = {"n": 0}
    real = py_mod.parse_python_file

    def counting(source):
        call_count["n"] += 1
        return real(source)

    monkeypatch.setattr(py_mod, "parse_python_file", counting)
    # Also patch the dispatcher which captured the original at import time
    from plugin.services import parsers as parsers_mod

    monkeypatch.setattr(parsers_mod, "parse_python_file", counting)

    rm.walk_and_cache()
    assert call_count["n"] == 0  # cache hit — no re-parse


def test_walk_reparses_after_content_change(store, project):
    pid = project[0].id
    _, root = project
    f = root / "a.py"
    f.write_text("def foo(): pass\n")
    rm = RepoMap(root, store, project_id=pid)
    rm.walk_and_cache()

    # Modify content + bump mtime
    import os

    f.write_text("def bar(): pass\n")
    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 10))

    files = rm.walk_and_cache()
    assert files[0].functions[0].name == "bar"


def test_walk_drops_deleted_files_from_cache(store, project):
    pid = project[0].id
    _, root = project
    a = root / "a.py"
    b = root / "b.py"
    a.write_text("def x(): pass\n")
    b.write_text("def y(): pass\n")
    rm = RepoMap(root, store, project_id=pid)
    rm.walk_and_cache()
    assert len(store.list_repo_map_entries(pid)) == 2
    b.unlink()
    rm.walk_and_cache()
    rows = store.list_repo_map_entries(pid)
    assert [r.file_path for r in rows] == ["a.py"]


def test_walk_raises_when_root_missing(store, tmp_path):
    p = store.create_project("p", str(tmp_path / "does_not_exist"), None)
    rm = RepoMap(Path(p.root_path), store, project_id=p.id)
    with pytest.raises(ProjectRootNotAccessible):
        rm.walk_and_cache()


def test_walk_returns_empty_for_empty_project(store, project):
    _, root = project
    rm = RepoMap(root, store, project_id=project[0].id)
    assert rm.walk_and_cache() == []


def test_walk_treats_stale_payload_version_as_cache_miss(store, project):
    """A row with v != _PAYLOAD_VERSION must be ignored and re-parsed."""
    pid = project[0].id
    _, root = project
    f = root / "a.py"
    f.write_text("def foo(): pass\n")
    # Seed a stale-version row at the current mtime so the mtime-hit branch
    # would normally return it without parsing.
    mtime = f.stat().st_mtime
    import hashlib
    sha1 = hashlib.sha1(f.read_bytes()).hexdigest()
    store.upsert_repo_map_entry(
        pid, "a.py", mtime, sha1,
        '{"v":999,"lines":1,"imports":[],"classes":[],"functions":[]}',
    )

    from plugin.services.repo_map import RepoMap
    rm = RepoMap(root, store, project_id=pid)
    files = rm.walk_and_cache()
    # Stale v=999 row must be rejected; the walker re-parses and gets `foo`.
    assert files[0].functions[0].name == "foo"
