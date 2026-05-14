# scripts/tests/test_release.py
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def test_bump_plugin_json(tmp_path, monkeypatch):
    pj = tmp_path / "plugin.json"
    pj.write_text(json.dumps({"name": "balu_code", "version": "0.0.1", "other": "x"}))
    import scripts.release as rel

    monkeypatch.setattr(rel, "PLUGIN_JSON", pj)
    rel.bump_plugin_json("0.1.0")
    data = json.loads(pj.read_text())
    assert data["version"] == "0.1.0"
    assert data["other"] == "x"  # other fields preserved


def test_check_clean_tree_passes_on_clean(monkeypatch):
    import scripts.release as rel

    monkeypatch.setattr(rel, "run", lambda cmd, **kw: "")
    rel.check_clean_tree()  # must not raise


def test_check_clean_tree_fails_on_dirty(monkeypatch):
    import scripts.release as rel

    monkeypatch.setattr(rel, "run", lambda cmd, **kw: " M plugin/plugin.json")
    with pytest.raises(SystemExit):
        rel.check_clean_tree()


def test_version_strip_v_prefix(tmp_path, monkeypatch):
    pj = tmp_path / "plugin.json"
    pj.write_text(json.dumps({"version": "0.0.1"}))
    import scripts.release as rel

    monkeypatch.setattr(rel, "PLUGIN_JSON", pj)
    monkeypatch.setattr(rel, "run", lambda *a, **kw: "")
    monkeypatch.setattr(rel, "check_clean_tree", lambda: None)
    with patch("sys.argv", ["release.py", "--version", "v0.1.0"]):
        rel.main()
    assert json.loads(pj.read_text())["version"] == "0.1.0"
