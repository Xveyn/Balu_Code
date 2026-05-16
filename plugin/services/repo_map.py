"""Token-budgeted, tree-sitter-driven repo map for the chat hot path.

Walks a project's root_path, caches symbols per file in the existing
repo_map_cache table (Phase-2 schema), and renders a budget-aware
overview to prepend to OpenCode user messages.
"""

from __future__ import annotations

from dataclasses import dataclass


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


__all__ = [
    "ClassSymbol",
    "FileSymbols",
    "FunctionSymbol",
    "ProjectRootNotAccessible",
    "RenderedMap",
    "RepoMapError",
]
