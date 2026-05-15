"""OpenCode server password lifecycle.

Lives at ``<data_dir>/runtime.password``. Generated on first call,
re-read on subsequent calls. The file mode is enforced to 0600 every
time we touch it, so a stray ``chmod`` from the user (or a previous
release that wrote it more loosely) gets repaired silently.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

_FILE_NAME = "runtime.password"
_MIN_BYTES = 32  # token_urlsafe(32) -> 43-char base64url string


def password_path(data_dir: Path) -> Path:
    return data_dir / _FILE_NAME


def load_or_create_password(data_dir: Path) -> str:
    """Return the persisted password, generating it on first call.

    Always leaves the file at mode 0600. Raises ``ValueError`` if a
    file exists but is empty (corrupt state — caller can decide to
    delete and retry).
    """
    target = password_path(data_dir)

    if target.exists():
        current_mode = stat.S_IMODE(target.stat().st_mode)
        if current_mode != 0o600:
            target.chmod(0o600)
        value = target.read_text().strip()
        if not value:
            raise ValueError(f"runtime password file is empty: {target}")
        return value

    data_dir.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(_MIN_BYTES)
    try:
        # O_CREAT|O_EXCL keeps two parallel BaluHost workers from clobbering
        # each other's freshly-generated password during simultaneous boot.
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # The other worker won the race; re-enter to read what they wrote.
        return load_or_create_password(data_dir)
    try:
        os.write(fd, value.encode("utf-8"))
    finally:
        os.close(fd)
    return value


__all__ = ["load_or_create_password", "password_path"]
