# plugin/tests/test_opencode_runtime.py
from __future__ import annotations

import re

import pytest

from plugin.services import opencode_runtime as rt


def test_pinned_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", rt.OPENCODE_VERSION)


def test_checksums_dict_has_linux_x86_64():
    assert "linux-x86_64" in rt.BINARY_CHECKSUMS
    assert rt.BINARY_CHECKSUMS["linux-x86_64"].startswith("sha256:")


def test_target_triple_detects_linux_x86_64(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    assert rt.detect_target_triple() == "linux-x86_64"


def test_target_triple_rejects_unsupported(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "armv7l")
    with pytest.raises(rt.UnsupportedPlatformError):
        rt.detect_target_triple()
