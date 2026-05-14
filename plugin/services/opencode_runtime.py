"""opencode runtime lifecycle: binary download, subprocess, health, watchdog.

Pinned to a specific opencode version. Bumping the version is an explicit
plugin release step: update OPENCODE_VERSION and BINARY_CHECKSUMS, run the
integration smoke test, ship.
"""
from __future__ import annotations

import platform

OPENCODE_VERSION = "0.6.0"  # bump per release; verify checksums when bumping

# sha256 of the standalone binaries from upstream GitHub releases.
# Populated in Task 4 with real values. Placeholders are intentional config
# values, not unfinished plan items — they get filled at release time.
BINARY_CHECKSUMS: dict[str, str] = {
    "linux-x86_64": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
}


class UnsupportedPlatformError(RuntimeError):
    """Raised when running on a platform with no published opencode binary."""


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


__all__ = [
    "BINARY_CHECKSUMS",
    "OPENCODE_VERSION",
    "UnsupportedPlatformError",
    "detect_target_triple",
]
