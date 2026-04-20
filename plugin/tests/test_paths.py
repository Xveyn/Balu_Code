"""Tests for path-containment helper."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from plugin.services.paths import PathEscapesProjectError, resolve_within_project


def test_happy_path_relative_file(tmp_path: Path) -> None:
    target = tmp_path / "src" / "foo.py"
    target.parent.mkdir()
    target.write_text("x")
    resolved = resolve_within_project(tmp_path, "src/foo.py")
    assert resolved == (tmp_path / "src" / "foo.py").resolve()


def test_happy_path_file_that_does_not_exist_yet(tmp_path: Path) -> None:
    resolved = resolve_within_project(tmp_path, "new/file.py")
    assert resolved == (tmp_path / "new" / "file.py").resolve()


def test_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within_project(tmp_path, "/etc/passwd")


def test_rejects_dotdot_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within_project(tmp_path, "../outside.py")


def test_rejects_embedded_dotdot(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within_project(tmp_path, "src/../../escape.py")


def test_rejects_empty_path(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within_project(tmp_path, "")


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-target"
    outside.mkdir(exist_ok=True)
    try:
        link = tmp_path / "escape-link"
        os.symlink(outside, link)
        with pytest.raises(PathEscapesProjectError):
            resolve_within_project(tmp_path, "escape-link/secret.txt")
    finally:
        if outside.exists():
            for child in outside.iterdir():
                child.unlink()
            outside.rmdir()


def test_normalises_redundant_separators(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.txt").write_text("x")
    resolved = resolve_within_project(tmp_path, "a//b.txt")
    assert resolved == (tmp_path / "a" / "b.txt").resolve()


def test_rejects_null_byte(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within_project(tmp_path, "foo\x00bar")


def test_rejects_windows_drive_letter_backslash(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within_project(tmp_path, "C:\\foo.txt")


def test_rejects_windows_drive_letter_forward(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within_project(tmp_path, "C:/foo.txt")


def test_rejects_unc_path(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within_project(tmp_path, "\\\\server\\share\\file.txt")
