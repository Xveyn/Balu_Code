"""Token-budgeted, tree-sitter-driven repo map for the chat hot path.

Walks a project's root_path, caches symbols per file in the existing
repo_map_cache table (Phase-2 schema), and renders a budget-aware
overview to prepend to OpenCode user messages.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from plugin.services.project_store import ProjectStore

_SOURCE_EXTENSIONS = frozenset({".py", ".js", ".jsx", ".ts", ".tsx"})
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
        "out",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "htmlcov",
        ".tox",
        ".next",
        ".nuxt",
        ".turbo",
        "coverage",
    }
)
_IGNORE_SUFFIX_GLOBS = (".min.js", ".d.ts")
_PAYLOAD_VERSION = 1


@dataclass(frozen=True)
class ClassSymbol:
    name: str
    bases: list[str]
    methods: list[str]


@dataclass(frozen=True)
class FunctionSymbol:
    name: str
    signature: str


@dataclass(frozen=True)
class FileSymbols:
    path: str
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


class RepoMapError(Exception):
    """Base for repo-map errors."""


class ProjectRootNotAccessible(RepoMapError):
    """Raised when the project root does not exist or is not a directory."""


def _is_source_file(name: str) -> bool:
    if any(name.endswith(s) for s in _IGNORE_SUFFIX_GLOBS):
        return False
    suffix = Path(name).suffix
    return suffix in _SOURCE_EXTENSIONS


def _iter_source_files(project_root: Path):
    """Yield (absolute_path, relpath_posix) for every supported source file."""
    stack: list[Path] = [project_root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (PermissionError, FileNotFoundError):
            continue
        for entry in entries:
            if entry.is_dir() and not entry.is_symlink():
                if entry.name in _IGNORE_DIRS:
                    continue
                if entry.name.startswith(".") and entry.name not in {"."}:
                    continue
                stack.append(entry)
            elif entry.is_file() and _is_source_file(entry.name):
                rel = entry.relative_to(project_root).as_posix()
                yield entry, rel


def _serialize_symbols(
    lines: int,
    imports: list[str],
    classes: list[ClassSymbol],
    functions: list[FunctionSymbol],
) -> str:
    return json.dumps(
        {
            "v": _PAYLOAD_VERSION,
            "lines": lines,
            "imports": imports,
            "classes": [
                {"name": c.name, "bases": c.bases, "methods": c.methods}
                for c in classes
            ],
            "functions": [
                {"name": f.name, "signature": f.signature} for f in functions
            ],
        },
        separators=(",", ":"),
    )


def _deserialize_symbols(blob: str, relpath: str) -> FileSymbols:
    raw = json.loads(blob)
    if raw.get("v") != _PAYLOAD_VERSION:
        raise ValueError(
            f"repo_map cache version mismatch: expected {_PAYLOAD_VERSION}, got {raw.get('v')!r}"
        )
    return FileSymbols(
        path=relpath,
        lines=raw.get("lines", 0),
        imports=list(raw.get("imports", [])),
        classes=[
            ClassSymbol(name=c["name"], bases=list(c["bases"]), methods=list(c["methods"]))
            for c in raw.get("classes", [])
        ],
        functions=[
            FunctionSymbol(name=f["name"], signature=f["signature"])
            for f in raw.get("functions", [])
        ],
    )


class RepoMap:
    """Walks a project root, caches parsed symbols, renders a budget-aware map."""

    def __init__(self, project_root: Path, store: ProjectStore, project_id: int) -> None:
        self._root = project_root
        self._store = store
        self._pid = project_id

    def walk_and_cache(self) -> list[FileSymbols]:
        if not self._root.exists() or not self._root.is_dir():
            raise ProjectRootNotAccessible(str(self._root))

        # Index existing cache rows by file_path for O(1) lookup.
        existing = {r.file_path: r for r in self._store.list_repo_map_entries(self._pid)}

        from plugin.services.parsers import parse_file  # local import: avoid cycles

        visited: set[str] = set()
        results: list[FileSymbols] = []

        for fs_path, relpath in _iter_source_files(self._root):
            visited.add(relpath)
            try:
                mtime = fs_path.stat().st_mtime
            except OSError:
                continue

            def _try_deserialize(row) -> FileSymbols | None:
                try:
                    return _deserialize_symbols(row.symbols_json, relpath)
                except ValueError:
                    return None

            cached = existing.get(relpath)
            if cached is not None and abs(cached.mtime - mtime) < 1e-6:
                fs = _try_deserialize(cached)
                if fs is not None:
                    results.append(fs)
                    continue

            try:
                raw = fs_path.read_bytes()
            except OSError:
                continue

            sha1 = hashlib.sha1(raw).hexdigest()

            if cached is not None and cached.sha1 == sha1:
                # mtime touched without content change: refresh mtime, reuse symbols.
                fs = _try_deserialize(cached)
                if fs is not None:
                    self._store.upsert_repo_map_entry(
                        self._pid, relpath, mtime, sha1, cached.symbols_json
                    )
                    results.append(fs)
                    continue

            extension = fs_path.suffix
            imports, classes, functions = parse_file(raw, extension)
            line_count = raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)
            blob = _serialize_symbols(line_count, imports, classes, functions)
            self._store.upsert_repo_map_entry(self._pid, relpath, mtime, sha1, blob)
            results.append(
                FileSymbols(
                    path=relpath,
                    lines=line_count,
                    imports=imports,
                    classes=classes,
                    functions=functions,
                )
            )

        self._store.delete_repo_map_entries(self._pid, visited)
        return results

    @staticmethod
    def render(
        files: list[FileSymbols],
        *,
        budget_tokens: int = 2048,
        project_name: str = "",
    ) -> RenderedMap:
        # Implemented in Task 11.
        raise NotImplementedError


__all__ = [
    "ClassSymbol",
    "FileSymbols",
    "FunctionSymbol",
    "ProjectRootNotAccessible",
    "RenderedMap",
    "RepoMap",
    "RepoMapError",
]
