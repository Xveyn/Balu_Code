"""Domain types used by the repo-map walker and language extractors.

These types live in their own module so ``repo_map.py`` (the walker) and
``repo_map_python.py`` (the Python parser) can each import them without
forming an import cycle. Future per-language extractors do the same.

The dataclasses below are ``frozen=True`` to signal that callers should
not mutate them; the ``list`` fields are still technically mutable and
the dataclasses are not hashable. Treat them as immutable by convention.
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


__all__ = [
    "ClassSymbol",
    "FileSymbols",
    "FunctionSymbol",
    "ProjectRootNotAccessible",
    "RenderedMap",
    "RepoMapError",
]
