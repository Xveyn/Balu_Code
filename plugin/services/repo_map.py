"""Runtime entry point for the repo-map walker.

This module is intentionally language-agnostic. Per-language extractors
live in sibling modules (``repo_map_python.py``, future ``repo_map_ts.py``,
etc.) and return the dataclasses defined in ``repo_map_types.py``.

Phase 3a ships only the types and the public surface skeleton; the
``RepoMap`` class with ``walk_and_cache`` and ``render`` is added in
Tasks 6 and 7.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from plugin.services.project_store import ProjectStore
from plugin.services.repo_map_python import parse_python_file
from plugin.services.repo_map_types import (
    ClassSymbol,
    FileSymbols,
    FunctionSymbol,
    ProjectRootNotAccessible,
    RenderedMap,
    RepoMapError,
)

_IGNORE_DIRS = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "node_modules",
        ".git",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "target",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "htmlcov",
        ".tox",
    }
)


def _is_ignored(rel_parts: tuple[str, ...]) -> bool:
    return any(p in _IGNORE_DIRS for p in rel_parts)


def _serialize_symbols(
    imports: list[str], classes: list[ClassSymbol], functions: list[FunctionSymbol]
) -> str:
    return json.dumps(
        {
            "imports": imports,
            "classes": [
                {"name": c.name, "bases": list(c.bases), "methods": list(c.methods)}
                for c in classes
            ],
            "functions": [{"name": f.name, "signature": f.signature} for f in functions],
        }
    )


def _deserialize_symbols(
    blob: str,
) -> tuple[list[str], list[ClassSymbol], list[FunctionSymbol]]:
    data = json.loads(blob)
    imports = list(data.get("imports", []))
    classes = [
        ClassSymbol(name=c["name"], bases=list(c["bases"]), methods=list(c["methods"]))
        for c in data.get("classes", [])
    ]
    functions = [
        FunctionSymbol(name=f["name"], signature=f["signature"]) for f in data.get("functions", [])
    ]
    return imports, classes, functions


class RepoMap:
    """Walk a project root, populate ``repo_map_cache``, return per-file symbols."""

    def __init__(self, project_root: Path, store: ProjectStore, project_id: int) -> None:
        self._root = project_root
        self._store = store
        self._project_id = project_id

    def walk_and_cache(self) -> list[FileSymbols]:
        if not self._root.exists() or not self._root.is_dir():
            raise ProjectRootNotAccessible(str(self._root))

        cached_by_path = {
            row.file_path: row for row in self._store.list_repo_map_entries(self._project_id)
        }

        results: list[FileSymbols] = []
        seen_paths: set[str] = set()

        for fs_path in self._root.rglob("*.py"):
            if not fs_path.is_file():
                continue
            rel = fs_path.relative_to(self._root)
            if _is_ignored(rel.parts):
                continue
            rel_posix = rel.as_posix()
            seen_paths.add(rel_posix)

            content_bytes = fs_path.read_bytes()
            mtime = fs_path.stat().st_mtime
            # Always compute sha1: sub-second writes can leave mtime unchanged on
            # some filesystems, so mtime is not a reliable cache key. The read +
            # hash overhead is small compared to a tree-sitter parse.
            sha1 = hashlib.sha1(content_bytes).hexdigest()
            cached = cached_by_path.get(rel_posix)
            if cached is not None and cached.sha1 == sha1:
                # Content unchanged — use cached symbols.
                imports, classes, functions = _deserialize_symbols(cached.symbols_json)
                if cached.mtime != mtime:
                    # Mtime drifted but content is the same; update mtime in cache.
                    self._store.upsert_repo_map_entry(
                        project_id=self._project_id,
                        file_path=rel_posix,
                        mtime=mtime,
                        sha1=sha1,
                        symbols_json=cached.symbols_json,
                    )
            else:
                # Content changed or not cached — parse.
                imports, classes, functions = parse_python_file(content_bytes)
                self._store.upsert_repo_map_entry(
                    project_id=self._project_id,
                    file_path=rel_posix,
                    mtime=mtime,
                    sha1=sha1,
                    symbols_json=_serialize_symbols(imports, classes, functions),
                )

            line_count = content_bytes.count(b"\n") + (
                0 if content_bytes.endswith(b"\n") or not content_bytes else 1
            )
            results.append(
                FileSymbols(
                    path=rel_posix,
                    lines=line_count,
                    imports=imports,
                    classes=classes,
                    functions=functions,
                )
            )

        # Drop cache rows for files that disappeared.
        self._store.delete_repo_map_entries(self._project_id, seen_paths)
        return results


__all__ = [
    "ClassSymbol",
    "FileSymbols",
    "FunctionSymbol",
    "ProjectRootNotAccessible",
    "RenderedMap",
    "RepoMap",
    "RepoMapError",
]
