"""Repo-map walker and Aider-style formatter.

Hosts ``RepoMap``, the language-agnostic walker. Per-language symbol
extractors live in sibling modules (``repo_map_python.py``, future
``repo_map_ts.py``, etc.). The shared dataclasses + exception types
live in ``repo_map_types.py`` and are re-exported here for caller
convenience.

``RepoMap.walk_and_cache`` enumerates the project tree, fingerprints
files via sha1, and persists per-file symbol snapshots in the
``repo_map_cache`` SQLite table. ``RepoMap.render`` produces a budget-
bounded text block ready for inclusion in an LLM prompt.
"""

from __future__ import annotations

import hashlib
import json
import os
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

IGNORE_DIRS = frozenset(
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
    return any(p in IGNORE_DIRS for p in rel_parts)


def _format_file_block(fs: FileSymbols) -> str:
    """Render one file as the Aider-style block."""
    lines = [f"=== {fs.path} ({fs.lines} lines)\n"]
    if fs.imports:
        lines.append(f"imports: {', '.join(fs.imports)}\n")
    if fs.classes:
        lines.append("classes:\n")
        for cls in fs.classes:
            base_part = f"({', '.join(cls.bases)})" if cls.bases else ""
            lines.append(f"  class {cls.name}{base_part}:\n")
            for method in cls.methods:
                lines.append(f"    {method}\n")
    if fs.functions:
        lines.append("functions:\n")
        for fn in fs.functions:
            lines.append(f"  {fn.signature}\n")
    return "".join(lines)


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

        for dirpath_str, dirnames, filenames in os.walk(self._root):
            # Prune ignored directories *before* descending into them.
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
            dirpath = Path(dirpath_str)
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                fs_path = dirpath / fname
                if not fs_path.is_file():
                    continue
                rel = fs_path.relative_to(self._root)
                # Defensive: still check on the file-name level in case the
                # root itself sits inside an ignored-named directory.
                if _is_ignored(rel.parts):
                    continue
                rel_posix = rel.as_posix()
                seen_paths.add(rel_posix)

                mtime = fs_path.stat().st_mtime
                content_bytes = fs_path.read_bytes()
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

    @staticmethod
    def render(files: list[FileSymbols], budget_tokens: int = 6144) -> RenderedMap:
        """Render an Aider-style block per file until the budget is exhausted.

        Token budget is approximated as ``len(text) // 4`` (a coarse but
        well-known heuristic). Files included up to the budget appear in
        the text; the rest are listed in ``truncated_files``. Files are
        ordered alphabetically by path.

        The first file (in alphabetical order) is always included even
        when its rendered block exceeds the budget on its own. Callers
        that need an empty render for a zero-file input should pass an
        empty list.
        """
        sorted_files = sorted(files, key=lambda f: f.path)
        budget_chars = budget_tokens * 4
        chunks: list[str] = []
        included_count = 0
        truncated: list[str] = []
        cursor = 0

        for fs in sorted_files:
            block = _format_file_block(fs)
            if cursor + len(block) > budget_chars and chunks:
                truncated.append(fs.path)
                continue
            chunks.append(block)
            cursor += len(block)
            included_count += 1

        # We `continue` (not `break`) on over-budget so that smaller later
        # files which might still fit get a chance. In practice the outer
        # comparison is monotonic once the budget is tight, but the loop
        # shape is cheap and keeps `truncated_files` complete.
        text = "".join(chunks)
        return RenderedMap(
            text=text,
            file_count=included_count,
            truncated_files=truncated,
            total_bytes=len(text),
        )


__all__ = [
    "IGNORE_DIRS",
    "ProjectRootNotAccessible",
    "RepoMap",
    "RepoMapError",
]
