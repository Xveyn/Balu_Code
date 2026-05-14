# plugin/tests/test_opencode_runtime.py
from __future__ import annotations

import re

import httpx
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


def test_binary_path_under_data_dir(tmp_path):
    bin_path = rt.binary_path(tmp_path)
    assert bin_path == tmp_path / "runtime" / "opencode-linux-x86_64"


@pytest.mark.asyncio
async def test_ensure_binary_downloads_when_missing(tmp_path, monkeypatch):
    import hashlib as _h
    fake_bytes = b"#!/bin/sh\necho fake opencode\n"
    fake_checksum = "sha256:" + _h.sha256(fake_bytes).hexdigest()
    monkeypatch.setitem(rt.BINARY_CHECKSUMS, "linux-x86_64", fake_checksum)

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "opencode" in str(request.url)
        return httpx.Response(200, content=fake_bytes)

    transport = httpx.MockTransport(mock_handler)
    bin_path = await rt.ensure_binary(tmp_path, transport=transport)
    assert bin_path.exists()
    assert bin_path.read_bytes() == fake_bytes
    assert bin_path.stat().st_mode & 0o111  # executable bit set


@pytest.mark.asyncio
async def test_ensure_binary_skips_when_present_and_valid(tmp_path, monkeypatch):
    import hashlib as _h
    fake_bytes = b"#!/bin/sh\necho cached\n"
    fake_checksum = "sha256:" + _h.sha256(fake_bytes).hexdigest()
    monkeypatch.setitem(rt.BINARY_CHECKSUMS, "linux-x86_64", fake_checksum)

    bin_path = rt.binary_path(tmp_path)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(fake_bytes)
    bin_path.chmod(0o755)

    async def fail_handler(request):
        raise AssertionError("must not download when cached")

    transport = httpx.MockTransport(fail_handler)
    result = await rt.ensure_binary(tmp_path, transport=transport)
    assert result == bin_path
