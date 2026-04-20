"""Project-root path-containment helper.

Used by every file-system-touching tool. Rejects absolute paths, ``..``
traversal (including via symlinks), and empty inputs. Works for both
existing and not-yet-existing targets — creation is a valid use case.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


class PathEscapesProjectError(ValueError):
    """The requested path would escape the project root."""


def resolve_within_project(project_root: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` relative to ``project_root`` and verify containment."""
    if not rel_path or rel_path != rel_path.strip():
        raise PathEscapesProjectError(f"path must be a non-empty trimmed string, got {rel_path!r}")

    if PurePosixPath(rel_path).is_absolute() or Path(rel_path).is_absolute():
        raise PathEscapesProjectError(f"path '{rel_path}' is absolute")

    root_resolved = project_root.resolve(strict=False)
    candidate = (root_resolved / rel_path).resolve(strict=False)

    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise PathEscapesProjectError(
            f"path '{rel_path}' escapes project root {root_resolved}"
        ) from exc

    return candidate


__all__ = ["PathEscapesProjectError", "resolve_within_project"]
