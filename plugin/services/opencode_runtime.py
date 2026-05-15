"""opencode runtime lifecycle: binary download, subprocess, health, watchdog.

Pinned to a specific opencode version. Bumping the version is an explicit
plugin release step: update OPENCODE_VERSION and BINARY_CHECKSUMS, run the
integration smoke test, ship.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import io
import os
import platform
import signal
import tarfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

_spawn = asyncio.create_subprocess_exec  # safe API — no shell

OPENCODE_VERSION = "1.14.50"  # bump per release; verify checksums when bumping

# sha256 of the *extracted* binaries from upstream GitHub releases.
# Upstream project: https://github.com/sst/opencode
# Checksum is computed against the binary AFTER extraction from the archive.
BINARY_CHECKSUMS: dict[str, str] = {
    "linux-x86_64": "sha256:2c4abf29d5765f535f10ffec748aa38939d5441750abbdb5001a4307d33349ae",
}


class UnsupportedPlatformError(RuntimeError):
    """Raised when running on a platform with no published opencode binary."""


class ChecksumMismatchError(RuntimeError):
    """Downloaded binary did not match pinned checksum."""


def detect_target_triple() -> str:
    """Return opencode binary target identifier for this host.

    Currently only `linux-x86_64` is supported by this plugin. Add other
    triples here as binaries are verified.
    """
    system = platform.system()
    machine = platform.machine()
    if system == "Linux" and machine == "x86_64":
        return "linux-x86_64"
    raise UnsupportedPlatformError(f"unsupported platform: {system}/{machine}")


# Map our internal triple names to upstream asset filename suffixes
_UPSTREAM_TRIPLE: dict[str, str] = {
    "linux-x86_64": "linux-x64",
}

_DOWNLOAD_URL_TEMPLATE = (
    "https://github.com/sst/opencode/releases/download/v{version}/opencode-{asset_triple}.tar.gz"
)


def binary_path(data_dir: Path) -> Path:
    """Where the active opencode binary lives inside the plugin data dir."""
    return data_dir / "runtime" / f"opencode-{detect_target_triple()}"


async def ensure_binary(
    data_dir: Path,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Path:
    """Return path to a valid opencode binary, downloading if needed."""
    target = binary_path(data_dir)
    expected_checksum = BINARY_CHECKSUMS[detect_target_triple()]

    if target.exists() and _verify_checksum(target, expected_checksum):
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    triple = detect_target_triple()
    url = _DOWNLOAD_URL_TEMPLATE.format(
        version=OPENCODE_VERSION, asset_triple=_UPSTREAM_TRIPLE[triple]
    )
    async with httpx.AsyncClient(
        transport=transport, timeout=120.0, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.content

    # Extract the opencode binary from the tarball
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = [
            m for m in tar.getmembers() if m.isfile() and m.name.rstrip("/").endswith("opencode")
        ]
        if not members:
            raise RuntimeError("no opencode binary found inside tarball")
        f = tar.extractfile(members[0])
        if f is None:
            raise RuntimeError("could not extract opencode binary from tarball")
        data = f.read()

    actual = "sha256:" + hashlib.sha256(data).hexdigest()
    if actual != expected_checksum:
        raise ChecksumMismatchError(
            f"opencode binary checksum mismatch: expected {expected_checksum}, got {actual}"
        )

    target.write_bytes(data)
    target.chmod(0o755)
    return target


def _verify_checksum(path: Path, expected: str) -> bool:
    actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return actual == expected


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


@dataclass
class ServerHandle:
    process: asyncio.subprocess.Process | None  # None = attached, not owned
    port: int
    log_fd: int | None  # None when attached
    lock_fd: int | None = None  # Owner-only: holds the spawn lock; released on process exit

    @property
    def pid(self) -> int:
        if self.process is None:
            return 0  # attached — no owning process
        return self.process.pid

    @property
    def owned(self) -> bool:
        return self.process is not None


async def start_server(
    *,
    binary: Path,
    config_dir: Path,
    log_path: Path,
    port: int = 4096,
    hostname: str = "127.0.0.1",
    ready_timeout: float = 15.0,
    password: str | None = None,
) -> ServerHandle:
    """Spawn `opencode serve --port <port> --hostname <host>` with OPENCODE_CONFIG_DIR
    pointing at `config_dir`, then poll /global/health until ready.

    When ``password`` is set, ``OPENCODE_SERVER_PASSWORD`` is exported into
    the child env, which enables HTTP Basic Auth on every endpoint. The
    health probe uses the same credentials so readiness still resolves.

    opencode v1.14.50 has no --config flag; configuration is loaded from
    `<OPENCODE_CONFIG_DIR>/opencode.json` (or `.opencode/` subdirectory).
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("ab")
    log_fd = log_file.fileno()

    env = {**os.environ, "OPENCODE_CONFIG_DIR": str(config_dir)}
    if password is not None:
        env["OPENCODE_SERVER_PASSWORD"] = password
    else:
        env.pop("OPENCODE_SERVER_PASSWORD", None)
    proc = await _spawn(
        str(binary),
        "serve",
        "--port",
        str(port),
        "--hostname",
        hostname,
        stdout=log_fd,
        stderr=log_fd,
        stdin=asyncio.subprocess.DEVNULL,
        env=env,
    )

    actual_port = port if port > 0 else _read_port_from_log(log_path, timeout=5.0)
    healthy = await _wait_for_health(
        hostname, actual_port, timeout=ready_timeout, password=password
    )
    if not healthy:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except TimeoutError:
            proc.kill()
        raise RuntimeError(
            f"opencode server did not become healthy within {ready_timeout}s — " f"check {log_path}"
        )
    return ServerHandle(process=proc, port=actual_port, log_fd=log_fd)


async def stop_server(handle: ServerHandle, *, grace_seconds: float = 5.0) -> None:
    """SIGTERM, wait grace, SIGKILL if needed."""
    if handle.process is None:
        return  # attached; don't kill someone else's opencode
    if handle.process.returncode is not None:
        return
    handle.process.send_signal(signal.SIGTERM)
    try:
        await asyncio.wait_for(handle.process.wait(), timeout=grace_seconds)
    except TimeoutError:
        handle.process.kill()
        await handle.process.wait()


async def _wait_for_health(
    host: str, port: int, timeout: float, *, password: str | None = None
) -> bool:
    """Poll GET /global/health until 200 or timeout."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    auth = httpx.BasicAuth("opencode", password) if password else None
    async with httpx.AsyncClient(timeout=2.0, auth=auth) as client:
        while loop.time() < deadline:
            try:
                resp = await client.get(f"http://{host}:{port}/global/health")
                if resp.status_code == 200:
                    return True
            except (httpx.HTTPError, OSError):
                pass
            await asyncio.sleep(0.25)
    return False


def _read_port_from_log(log_path: Path, timeout: float) -> int:
    """When port=0 (OS-allocated), parse opencode stdout for the actual port.

    opencode v1.14.50 prints a line containing 'http://<host>:<port>' on startup.
    """
    import re

    deadline = time.monotonic() + timeout
    pattern = re.compile(r"http://[^:/\s]+:(\d+)")
    while time.monotonic() < deadline:
        if log_path.exists():
            for line in log_path.read_text(errors="ignore").splitlines():
                m = pattern.search(line)
                if m:
                    return int(m.group(1))
        time.sleep(0.1)
    raise RuntimeError(f"could not detect opencode port from log {log_path}")


# ---------------------------------------------------------------------------
# Multi-worker coordination
# ---------------------------------------------------------------------------


async def _probe_health(
    host: str, port: int, *, timeout: float, password: str | None = None
) -> bool:
    """One-shot health check. Returns True on 200, False otherwise (no waiting)."""
    auth = httpx.BasicAuth("opencode", password) if password else None
    async with httpx.AsyncClient(timeout=timeout, auth=auth) as client:
        try:
            resp = await client.get(f"http://{host}:{port}/global/health")
            return resp.status_code == 200
        except (httpx.HTTPError, OSError):
            return False


async def start_or_attach_server(
    *,
    binary: Path,
    config_dir: Path,
    log_path: Path,
    lock_path: Path,
    port: int = 4096,
    hostname: str = "127.0.0.1",
    ready_timeout: float = 20.0,
    password: str | None = None,
) -> ServerHandle:
    """Spawn opencode on `port` if no one else has, else attach to the running one.

    When ``password`` is provided, every health probe (initial attach check
    and the post-spawn wait) sends Basic Auth with username ``opencode``.
    The password is also injected into the child env so a freshly-spawned
    server runs in authenticated mode.
    """
    if await _probe_health(hostname, port, timeout=1.0, password=password):
        return ServerHandle(process=None, port=port, log_fd=None, lock_fd=None)

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        if await _wait_for_health(hostname, port, timeout=ready_timeout, password=password):
            return ServerHandle(process=None, port=port, log_fd=None, lock_fd=None)
        raise RuntimeError(
            f"opencode never reached healthy state on {hostname}:{port} after "
            f"{ready_timeout}s; another worker holds the lock but did not bring "
            f"the server up — check {log_path}"
        ) from None

    try:
        handle = await start_server(
            binary=binary,
            config_dir=config_dir,
            log_path=log_path,
            port=port,
            hostname=hostname,
            ready_timeout=ready_timeout,
            password=password,
        )
        handle.lock_fd = lock_fd
        return handle
    except Exception:
        os.close(lock_fd)
        raise


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------


@dataclass
class Watchdog:
    """Poll health on interval, restart on failure, give up after max_restarts in window."""

    is_healthy: Callable[[], bool] | Callable[[], Awaitable[bool]]
    restart: Callable[[], Awaitable[None]]
    poll_interval: float = 30.0
    max_restarts: int = 3
    window_seconds: float = 300.0
    _restart_timestamps: list[float] = field(default_factory=list)

    async def run(self) -> None:
        """Loop: poll health, restart on failure, give up after max_restarts/window."""
        while True:
            try:
                result = self.is_healthy()
                if asyncio.iscoroutine(result):
                    healthy = await result
                else:
                    healthy = bool(result)
            except Exception:
                healthy = False

            if not healthy:
                now = time.monotonic()
                self._restart_timestamps = [
                    t for t in self._restart_timestamps if now - t < self.window_seconds
                ]
                if len(self._restart_timestamps) >= self.max_restarts:
                    raise RuntimeError(
                        f"opencode runtime crashed {self.max_restarts} times in "
                        f"{self.window_seconds}s — entering degraded state"
                    )
                self._restart_timestamps.append(now)
                await self.restart()

            await asyncio.sleep(self.poll_interval)


__all__ = [
    "BINARY_CHECKSUMS",
    "ChecksumMismatchError",
    "OPENCODE_VERSION",
    "ServerHandle",
    "UnsupportedPlatformError",
    "Watchdog",
    "binary_path",
    "detect_target_triple",
    "ensure_binary",
    "start_or_attach_server",
    "start_server",
    "stop_server",
]
