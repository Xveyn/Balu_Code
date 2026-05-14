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
    import io
    import tarfile

    fake_binary = b"#!/bin/sh\necho fake opencode\n"
    fake_checksum = "sha256:" + _h.sha256(fake_binary).hexdigest()
    monkeypatch.setitem(rt.BINARY_CHECKSUMS, "linux-x86_64", fake_checksum)

    # Build an in-memory .tar.gz containing a file named "opencode"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="opencode")
        info.size = len(fake_binary)
        tar.addfile(info, io.BytesIO(fake_binary))
    tarball_bytes = buf.getvalue()

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "opencode" in str(request.url)
        return httpx.Response(200, content=tarball_bytes)

    transport = httpx.MockTransport(mock_handler)
    bin_path = await rt.ensure_binary(tmp_path, transport=transport)
    assert bin_path.exists()
    assert bin_path.read_bytes() == fake_binary
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


# ---------------------------------------------------------------------------
# Task 5: server lifecycle
# ---------------------------------------------------------------------------
import asyncio
import os


async def _stub_wait_healthy(host, port, timeout):
    return True


@pytest.mark.asyncio
async def test_start_server_spawns_subprocess(tmp_path, monkeypatch):
    fake = tmp_path / "runtime" / "opencode-linux-x86_64"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(0o755)

    cfg_dir = tmp_path  # directory containing opencode.json
    log = tmp_path / "opencode.log"

    monkeypatch.setattr(rt, "_wait_for_health", _stub_wait_healthy)
    monkeypatch.setattr(rt, "_read_port_from_log", lambda *a, **kw: 4096)

    handle = await rt.start_server(
        binary=fake, config_dir=cfg_dir, log_path=log, port=4096, ready_timeout=2.0
    )
    try:
        assert handle.pid > 0
        assert handle.port == 4096
    finally:
        await rt.stop_server(handle)


@pytest.mark.asyncio
async def test_stop_server_terminates_process(tmp_path, monkeypatch):
    fake = tmp_path / "runtime" / "opencode-linux-x86_64"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(0o755)
    cfg_dir = tmp_path
    log = tmp_path / "opencode.log"
    monkeypatch.setattr(rt, "_wait_for_health", _stub_wait_healthy)
    monkeypatch.setattr(rt, "_read_port_from_log", lambda *a, **kw: 4096)

    handle = await rt.start_server(
        binary=fake, config_dir=cfg_dir, log_path=log, port=4096, ready_timeout=2.0
    )
    await rt.stop_server(handle)
    with pytest.raises(ProcessLookupError):
        os.kill(handle.pid, 0)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.path.exists("/proc/self/environ"), reason="Linux /proc not available"
)
async def test_start_server_sets_opencode_config_dir_env(tmp_path, monkeypatch):
    """Verify start_server passes OPENCODE_CONFIG_DIR env var to child process."""
    fake = tmp_path / "runtime" / "opencode-linux-x86_64"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(0o755)
    cfg_dir = tmp_path / "configdir"
    cfg_dir.mkdir()
    log = tmp_path / "opencode.log"

    monkeypatch.setattr(rt, "_wait_for_health", _stub_wait_healthy)
    monkeypatch.setattr(rt, "_read_port_from_log", lambda *a, **kw: 4096)

    handle = await rt.start_server(
        binary=fake, config_dir=cfg_dir, log_path=log, port=4096, ready_timeout=2.0
    )
    try:
        await asyncio.sleep(0.1)
        import pathlib
        environ_file = pathlib.Path(f"/proc/{handle.pid}/environ")
        if environ_file.exists():
            env_data = environ_file.read_bytes().split(b"\x00")
            env_dict = dict(
                e.decode().split("=", 1) for e in env_data if b"=" in e
            )
            assert env_dict.get("OPENCODE_CONFIG_DIR") == str(cfg_dir)
    finally:
        await rt.stop_server(handle)


# ---------------------------------------------------------------------------
# Task 6: watchdog
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Multi-worker coordination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_or_attach_skips_spawn_when_already_healthy(tmp_path, monkeypatch):
    fake_binary = tmp_path / "runtime" / "opencode-linux-x86_64"
    fake_binary.parent.mkdir(parents=True)
    fake_binary.write_text("#!/bin/sh\necho should-not-run\n")
    fake_binary.chmod(0o755)
    cfg_dir = tmp_path
    log = tmp_path / "opencode.log"
    lock = tmp_path / "runtime.lock"

    async def probe_returns_true(host, port, *, timeout):
        return True

    monkeypatch.setattr(rt, "_probe_health", probe_returns_true)

    # If we tried to spawn, the fake binary would just print, but health
    # would not become true. Verify start_server is NOT called.
    spawn_called = []
    async def fail_start(*a, **kw):
        spawn_called.append(1)
        raise AssertionError("must not spawn when health already up")
    monkeypatch.setattr(rt, "start_server", fail_start)

    handle = await rt.start_or_attach_server(
        binary=fake_binary,
        config_dir=cfg_dir,
        log_path=log,
        lock_path=lock,
        port=4096,
        ready_timeout=1.0,
    )
    assert handle.owned is False
    assert handle.port == 4096
    assert handle.process is None
    # No need to stop — attached
    await rt.stop_server(handle)  # no-op


@pytest.mark.asyncio
async def test_start_or_attach_spawns_when_no_existing_server(tmp_path, monkeypatch):
    fake_binary = tmp_path / "runtime" / "opencode-linux-x86_64"
    fake_binary.parent.mkdir(parents=True)
    fake_binary.write_text("#!/bin/sh\nsleep 30\n")
    fake_binary.chmod(0o755)
    cfg_dir = tmp_path
    log = tmp_path / "opencode.log"
    lock = tmp_path / "runtime.lock"

    async def probe_returns_false(host, port, *, timeout):
        return False

    monkeypatch.setattr(rt, "_probe_health", probe_returns_false)
    monkeypatch.setattr(rt, "_wait_for_health", _stub_wait_healthy)
    monkeypatch.setattr(rt, "_read_port_from_log", lambda *a, **kw: 4096)

    handle = await rt.start_or_attach_server(
        binary=fake_binary,
        config_dir=cfg_dir,
        log_path=log,
        lock_path=lock,
        port=4096,
        ready_timeout=2.0,
    )
    try:
        assert handle.owned is True
        assert handle.process is not None
        assert handle.lock_fd is not None
    finally:
        await rt.stop_server(handle)


@pytest.mark.asyncio
async def test_start_or_attach_waits_when_lock_held(tmp_path, monkeypatch):
    import fcntl, os
    fake_binary = tmp_path / "runtime" / "opencode-linux-x86_64"
    fake_binary.parent.mkdir(parents=True)
    fake_binary.write_text("#!/bin/sh\necho noop\n")
    fake_binary.chmod(0o755)
    cfg_dir = tmp_path
    log = tmp_path / "opencode.log"
    lock = tmp_path / "runtime.lock"

    # Pre-acquire the lock as a "competing worker"
    other_fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(other_fd, fcntl.LOCK_EX)

    health_calls = []
    async def probe_returns_false(host, port, *, timeout):
        return False

    async def wait_returns_true_after_called(host, port, *, timeout):
        health_calls.append(1)
        return True

    monkeypatch.setattr(rt, "_probe_health", probe_returns_false)
    monkeypatch.setattr(rt, "_wait_for_health", wait_returns_true_after_called)

    handle = await rt.start_or_attach_server(
        binary=fake_binary,
        config_dir=cfg_dir,
        log_path=log,
        lock_path=lock,
        port=4096,
        ready_timeout=1.0,
    )
    assert handle.owned is False  # attached, didn't spawn
    assert len(health_calls) == 1

    # cleanup
    fcntl.flock(other_fd, fcntl.LOCK_UN)
    os.close(other_fd)


@pytest.mark.asyncio
async def test_watchdog_restarts_on_unhealthy():
    health_results = iter([True, False, True, True, True, True, True, True, True, True])
    restart_calls = []
    async def fake_restart():
        restart_calls.append(1)

    wd = rt.Watchdog(
        is_healthy=lambda: next(health_results),
        restart=fake_restart,
        poll_interval=0.02,
        max_restarts=3,
        window_seconds=5.0,
    )
    task = asyncio.create_task(wd.run())
    await asyncio.sleep(0.15)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(restart_calls) >= 1


@pytest.mark.asyncio
async def test_watchdog_gives_up_after_max_restarts():
    async def always_unhealthy():
        return False
    async def fake_restart():
        pass

    wd = rt.Watchdog(
        is_healthy=always_unhealthy,
        restart=fake_restart,
        poll_interval=0.01,
        max_restarts=2,
        window_seconds=5.0,
    )
    with pytest.raises(RuntimeError, match="degraded state"):
        await asyncio.wait_for(wd.run(), timeout=1.0)
