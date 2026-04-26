"""Project-root path-containment helper.

Used by every file-system-touching tool. Rejects absolute paths, ``..``
traversal (including via symlinks), and empty inputs. Works for both
existing and not-yet-existing targets — creation is a valid use case.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

_WINDOWS_ABS_RE = re.compile(r"^([A-Za-z]:[\\/]|\\\\)")


class PathEscapesProjectError(ValueError):
    """The requested path would escape the project root."""


def resolve_within_project(project_root: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` relative to ``project_root`` and verify containment."""
    if not rel_path or rel_path != rel_path.strip():
        raise PathEscapesProjectError(f"path must be a non-empty trimmed string, got {rel_path!r}")

    if "\x00" in rel_path:
        raise PathEscapesProjectError(f"path {rel_path!r} contains NUL byte")

    if PurePosixPath(rel_path).is_absolute():
        raise PathEscapesProjectError(f"path '{rel_path}' is absolute")

    if _WINDOWS_ABS_RE.match(rel_path):
        raise PathEscapesProjectError(f"path {rel_path!r} is a Windows-style absolute path")

    root_resolved = project_root.resolve(strict=False)
    candidate = (root_resolved / rel_path).resolve(strict=False)

    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise PathEscapesProjectError(f"path '{rel_path}' escapes the project root") from exc

    return candidate


__all__ = ["PathEscapesProjectError", "resolve_within_project"]
