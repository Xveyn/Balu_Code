"""Tests for the .bhplugin build script."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from scripts.build_bhplugin import build_bhplugin

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_build_produces_zip_with_plugin_json(tmp_path):
    artefact = build_bhplugin(REPO_ROOT, tmp_path)
    assert artefact.exists()
    assert artefact.suffix == ".bhplugin"
    with zipfile.ZipFile(artefact) as zf:
        names = set(zf.namelist())
    assert "plugin.json" in names


def test_build_includes_init_and_requirements(tmp_path):
    artefact = build_bhplugin(REPO_ROOT, tmp_path)
    with zipfile.ZipFile(artefact) as zf:
        names = set(zf.namelist())
    assert "__init__.py" in names
    assert "requirements.txt" in names


def test_build_vendors_balu_code_shared(tmp_path):
    artefact = build_bhplugin(REPO_ROOT, tmp_path)
    with zipfile.ZipFile(artefact) as zf:
        names = set(zf.namelist())
    assert any(
        n.startswith("balu_code_shared/") and n.endswith(".py") for n in names
    ), "expected vendored balu_code_shared/ tree"
    assert "balu_code_shared/events.py" in names


def test_build_excludes_tests_and_dev_pyproject(tmp_path):
    artefact = build_bhplugin(REPO_ROOT, tmp_path)
    with zipfile.ZipFile(artefact) as zf:
        names = set(zf.namelist())
    assert not any(n.startswith("tests/") for n in names)
    assert "pyproject.toml" not in names
    assert not any(n.endswith("__pycache__/") for n in names)


def test_build_emits_sha256_sidecar(tmp_path):
    artefact = build_bhplugin(REPO_ROOT, tmp_path)
    sidecar = artefact.with_suffix(artefact.suffix + ".sha256")
    assert sidecar.exists()
    expected = hashlib.sha256(artefact.read_bytes()).hexdigest()
    assert sidecar.read_text().strip().split()[0] == expected


def test_artefact_filename_includes_version(tmp_path):
    artefact = build_bhplugin(REPO_ROOT, tmp_path)
    manifest = json.loads((REPO_ROOT / "plugin" / "plugin.json").read_text())
    assert manifest["version"] in artefact.name
    assert artefact.name.startswith("balu_code-")
