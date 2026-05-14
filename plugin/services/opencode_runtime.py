"""opencode runtime lifecycle: binary download, subprocess, health, watchdog.

Pinned to a specific opencode version. Bumping the version is an explicit
plugin release step: update OPENCODE_VERSION and BINARY_CHECKSUMS, run the
integration smoke test, ship.
"""
from __future__ import annotations

import hashlib
import io
import platform
import tarfile
from pathlib import Path

import httpx

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
    async with httpx.AsyncClient(transport=transport, timeout=120.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.content

    # Extract the opencode binary from the tarball
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = [
            m for m in tar.getmembers()
            if m.isfile() and m.name.rstrip("/").endswith("opencode")
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


__all__ = [
    "BINARY_CHECKSUMS",
    "ChecksumMismatchError",
    "OPENCODE_VERSION",
    "UnsupportedPlatformError",
    "binary_path",
    "detect_target_triple",
    "ensure_binary",
]
