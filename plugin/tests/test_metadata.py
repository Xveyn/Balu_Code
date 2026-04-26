"""Tests for BaluCodePlugin metadata."""

from __future__ import annotations

import json
from pathlib import Path

from plugin import BaluCodePlugin


def test_plugin_name_is_balu_code():
    p = BaluCodePlugin()
    assert p.metadata.name == "balu_code"


def test_plugin_version_matches_plugin_json():
    p = BaluCodePlugin()
    manifest = json.loads((Path(__file__).parent.parent / "plugin.json").read_text())
    assert p.metadata.version == manifest["version"]


def test_plugin_required_permissions_match_manifest():
    p = BaluCodePlugin()
    manifest = json.loads((Path(__file__).parent.parent / "plugin.json").read_text())
    assert set(p.metadata.required_permissions) == set(manifest["required_permissions"])


def test_plugin_display_name():
    p = BaluCodePlugin()
    assert p.metadata.display_name == "Balu Code"


def test_plugin_category_is_general():
    p = BaluCodePlugin()
    assert p.metadata.category == "general"


def test_get_ui_manifest_returns_manifest_with_nav_item():
    from app.plugins.base import PluginUIManifest

    p = BaluCodePlugin()
    manifest = p.get_ui_manifest()
    assert isinstance(manifest, PluginUIManifest)
    assert manifest.bundle_path == "ui/bundle.js"
    assert len(manifest.nav_items) >= 1
    assert manifest.nav_items[0].label == "Balu Code"
