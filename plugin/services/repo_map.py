"""Domain types and runtime entry point for the repo-map walker.

This module is intentionally language-agnostic. Per-language extractors
live in sibling modules (``repo_map_python.py``, future ``repo_map_ts.py``,
etc.) and return the dataclasses defined here.

Phase 3a ships only the types and the public surface skeleton; the
``RepoMap`` class with ``walk_and_cache`` and ``render`` is added in
Tasks 6 and 7.
"""

from __future__ import annotations

from dataclasses import dataclass


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


__all__ = [
    "ClassSymbol",
    "FileSymbols",
    "FunctionSymbol",
    "ProjectRootNotAccessible",
    "RenderedMap",
    "RepoMapError",
]
