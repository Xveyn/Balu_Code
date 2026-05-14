"""opencode runtime lifecycle: binary download, subprocess, health, watchdog.

Pinned to a specific opencode version. Bumping the version is an explicit
plugin release step: update OPENCODE_VERSION and BINARY_CHECKSUMS, run the
integration smoke test, ship.
"""
from __future__ import annotations

import hashlib
import platform
from pathlib import Path

import httpx

OPENCODE_VERSION = "0.6.0"  # bump per release; verify checksums when bumping

# sha256 of the standalone binaries from upstream GitHub releases.
# Populated in Task 4 with real values. Placeholders are intentional config
# values, not unfinished plan items — they get filled at release time.
BINARY_CHECKSUMS: dict[str, str] = {
    "linux-x86_64": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
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


_DOWNLOAD_URL_TEMPLATE = (
    "https://github.com/sst/opencode/releases/download/v{version}/opencode-{triple}.tar.gz"
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
    url = _DOWNLOAD_URL_TEMPLATE.format(
        version=OPENCODE_VERSION, triple=detect_target_triple()
    )
    async with httpx.AsyncClient(transport=transport, timeout=120.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.content

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


__all__ = [
    "BINARY_CHECKSUMS",
    "ChecksumMismatchError",
    "OPENCODE_VERSION",
    "UnsupportedPlatformError",
    "binary_path",
    "detect_target_triple",
    "ensure_binary",
]
