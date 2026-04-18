"""Tests for the wheel build script."""

from __future__ import annotations

import zipfile
from pathlib import Path

from scripts.build_wheel import build_wheel

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_build_produces_wheel(tmp_path):
    artefact = build_wheel(REPO_ROOT, tmp_path)
    assert artefact.exists()
    assert artefact.suffix == ".whl"


def test_wheel_includes_main_module(tmp_path):
    artefact = build_wheel(REPO_ROOT, tmp_path)
    with zipfile.ZipFile(artefact) as zf:
        names = set(zf.namelist())
    assert any(n.endswith("balu_code_cli/__main__.py") for n in names)


def test_wheel_vendors_shared(tmp_path):
    artefact = build_wheel(REPO_ROOT, tmp_path)
    with zipfile.ZipFile(artefact) as zf:
        names = set(zf.namelist())
    # vendored as nested package `balu_code_cli._vendored.balu_code_shared`
    assert any("balu_code_shared/events.py" in n for n in names)


def test_cleanup_removes_vendored_dir_after_build(tmp_path):
    build_wheel(REPO_ROOT, tmp_path)
    vendored = REPO_ROOT / "cli" / "src" / "balu_code_cli" / "_vendored"
    assert not vendored.exists(), "vendored directory must be removed post-build"
