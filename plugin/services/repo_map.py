"""Domain types and runtime entry point for the repo-map walker.

This module is intentionally language-agnostic. Per-language extractors
live in sibling modules (``repo_map_python.py``, future ``repo_map_ts.py``,
etc.) and return the dataclasses defined here.

Phase 3a ships only the types and the public surface skeleton; the
``RepoMap`` class with ``walk_and_cache`` and ``render`` is added in
Tasks 6 and 7.

The dataclasses below are ``frozen=True`` to signal that callers should
not mutate them; the ``list`` fields are still technically mutable and
the dataclasses are not hashable. Treat them as immutable by convention.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from plugin.services.project_store import ProjectStore


class RepoMapError(Exception):
    """Base class for repo-map errors."""


class ProjectRootNotAccessible(RepoMapError):
    """Raised when the project's root_path does not exist or is not a directory."""


@dataclass(frozen=True)
class ClassSymbol:
    name: str
    bases: list[str]
    methods: list[str]  # rendered method signatures: 'def foo(self, x: int) -> str'


@dataclass(frozen=True)
class FunctionSymbol:
    name: str
    signature: str  # 'def bar(x: int = 1) -> None'


@dataclass(frozen=True)
class FileSymbols:
    path: str  # POSIX-style, relative to project root
    lines: int
    imports: list[str]
    classes: list[ClassSymbol]
    functions: list[FunctionSymbol]


@dataclass(frozen=True)
class RenderedMap:
    text: str
    file_count: int
    truncated_files: list[str]
    total_bytes: int


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
_IGNORE_SUFFIXES = frozenset({".pyc", ".pyo", ".so"})


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
            if rel.suffix in _IGNORE_SUFFIXES:
                continue
            rel_posix = rel.as_posix()
            seen_paths.add(rel_posix)

            content_bytes = fs_path.read_bytes()
            mtime = fs_path.stat().st_mtime
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


# Deferred to avoid circular import: repo_map_python imports ClassSymbol/FunctionSymbol
# from this module at its top level.  By deferring until our own dataclasses are fully
# defined, the partial-initialisation race is resolved.
from plugin.services.repo_map_python import parse_python_file  # noqa: E402, I001


__all__ = [
    "ClassSymbol",
    "FileSymbols",
    "FunctionSymbol",
    "ProjectRootNotAccessible",
    "RenderedMap",
    "RepoMap",
    "RepoMapError",
]
