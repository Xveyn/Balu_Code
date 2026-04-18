"""Tests for RepoMap.walk_and_cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from plugin.services.project_store import ProjectStore
from plugin.services.repo_map import (
    FileSymbols,
    ProjectRootNotAccessible,
    RepoMap,
)


@pytest.fixture
def store(tmp_path) -> ProjectStore:
    s = ProjectStore(tmp_path / "store.db")
    yield s
    s.close()


@pytest.fixture
def project_id(store) -> int:
    p = store.create_project(name="walker", root_path="/unused", config_yaml=None)
    return p.id


def _write(root: Path, rel: str, content: str) -> Path:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def test_raises_when_root_does_not_exist(tmp_path, store, project_id):
    rm = RepoMap(project_root=tmp_path / "missing", store=store, project_id=project_id)
    with pytest.raises(ProjectRootNotAccessible):
        rm.walk_and_cache()


def test_raises_when_root_is_a_file(tmp_path, store, project_id):
    f = tmp_path / "afile"
    f.write_text("hi")
    rm = RepoMap(project_root=f, store=store, project_id=project_id)
    with pytest.raises(ProjectRootNotAccessible):
        rm.walk_and_cache()


def test_walks_python_files_only(tmp_path, store, project_id):
    _write(tmp_path, "a.py", "def foo(): pass\n")
    _write(tmp_path, "b.txt", "ignored\n")
    _write(tmp_path, "sub/c.py", "def bar(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    files = sorted(rm.walk_and_cache(), key=lambda f: f.path)
    assert [f.path for f in files] == ["a.py", "sub/c.py"]
    assert all(isinstance(f, FileSymbols) for f in files)


def test_skips_ignored_directories(tmp_path, store, project_id):
    _write(tmp_path, "src/keep.py", "def k(): pass\n")
    _write(tmp_path, "__pycache__/ignored.py", "def x(): pass\n")
    _write(tmp_path, ".venv/lib/site-packages/dropped.py", "def y(): pass\n")
    _write(tmp_path, "node_modules/index.py", "def z(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    paths = {f.path for f in rm.walk_and_cache()}
    assert paths == {"src/keep.py"}


def test_second_walk_is_a_cache_hit_for_unchanged_files(tmp_path, store, project_id, monkeypatch):
    _write(tmp_path, "a.py", "def f(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    rm.walk_and_cache()  # populate cache

    parse_calls = []

    def counting_parse(source: bytes):
        parse_calls.append(source)
        from plugin.services.repo_map_python import parse_python_file as real

        return real(source)

    monkeypatch.setattr("plugin.services.repo_map.parse_python_file", counting_parse)
    rm2 = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    files = rm2.walk_and_cache()
    assert len(files) == 1
    assert parse_calls == []  # no re-parse on unchanged files


def test_mtime_change_without_content_change_skips_reparse(
    tmp_path, store, project_id, monkeypatch
):
    p = _write(tmp_path, "a.py", "def f(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    rm.walk_and_cache()

    # Touch the file to change mtime but not content.
    import os

    new_mtime = p.stat().st_mtime + 100
    os.utime(p, (new_mtime, new_mtime))

    parse_calls = []

    def counting_parse(source: bytes):
        parse_calls.append(source)
        from plugin.services.repo_map_python import parse_python_file as real

        return real(source)

    monkeypatch.setattr("plugin.services.repo_map.parse_python_file", counting_parse)
    rm2 = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    files = rm2.walk_and_cache()
    assert len(files) == 1
    assert parse_calls == []  # mtime drift but sha unchanged → no re-parse


def test_content_change_triggers_reparse(tmp_path, store, project_id, monkeypatch):
    p = _write(tmp_path, "a.py", "def old(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    rm.walk_and_cache()

    p.write_text("def new(): pass\n")

    parse_calls = []

    def counting_parse(source: bytes):
        parse_calls.append(source)
        from plugin.services.repo_map_python import parse_python_file as real

        return real(source)

    monkeypatch.setattr("plugin.services.repo_map.parse_python_file", counting_parse)
    rm2 = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    files = rm2.walk_and_cache()
    assert len(parse_calls) == 1
    assert files[0].functions[0].name == "new"


def test_deleted_file_drops_from_cache(tmp_path, store, project_id):
    p = _write(tmp_path, "a.py", "def f(): pass\n")
    _write(tmp_path, "b.py", "def g(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    rm.walk_and_cache()
    assert {r.file_path for r in store.list_repo_map_entries(project_id)} == {
        "a.py",
        "b.py",
    }

    p.unlink()
    rm.walk_and_cache()
    assert {r.file_path for r in store.list_repo_map_entries(project_id)} == {"b.py"}


def test_file_symbols_lines_count_matches_source(tmp_path, store, project_id):
    _write(tmp_path, "a.py", "x = 1\ny = 2\nz = 3\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    files = rm.walk_and_cache()
    assert files[0].lines == 3


def test_walking_empty_project_clears_cache(tmp_path, store, project_id):
    p = _write(tmp_path, "a.py", "def f(): pass\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    rm.walk_and_cache()
    assert {r.file_path for r in store.list_repo_map_entries(project_id)} == {"a.py"}

    p.unlink()
    rm.walk_and_cache()
    assert store.list_repo_map_entries(project_id) == []
