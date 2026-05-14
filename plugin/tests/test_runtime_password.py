"""Tests for the OpenCode runtime password lifecycle."""

from __future__ import annotations

import stat

import pytest

from plugin.services.runtime_password import load_or_create_password


def test_load_or_create_password_generates_when_missing(tmp_path):
    pw = load_or_create_password(tmp_path)
    assert isinstance(pw, str)
    assert len(pw) >= 32
    target = tmp_path / "runtime.password"
    assert target.exists()
    assert target.read_text() == pw


def test_load_or_create_password_is_idempotent(tmp_path):
    first = load_or_create_password(tmp_path)
    second = load_or_create_password(tmp_path)
    assert first == second


def test_load_or_create_password_sets_mode_0600(tmp_path):
    load_or_create_password(tmp_path)
    target = tmp_path / "runtime.password"
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_load_or_create_password_repairs_loose_permissions(tmp_path):
    target = tmp_path / "runtime.password"
    target.write_text("pre-existing-secret")
    target.chmod(0o644)
    pw = load_or_create_password(tmp_path)
    assert pw == "pre-existing-secret"
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_load_or_create_password_strips_trailing_whitespace(tmp_path):
    target = tmp_path / "runtime.password"
    target.write_text("abc-secret\n")
    target.chmod(0o600)
    assert load_or_create_password(tmp_path) == "abc-secret"


def test_load_or_create_password_rejects_empty_file(tmp_path):
    target = tmp_path / "runtime.password"
    target.write_text("")
    target.chmod(0o600)
    with pytest.raises(ValueError):
        load_or_create_password(tmp_path)


def test_load_or_create_password_handles_concurrent_create(tmp_path):
    """Simulate the race where another worker created the file between our
    'exists?' check and our O_CREAT|O_EXCL open: the second caller must
    fall back to reading instead of raising FileExistsError."""
    import os as _os

    target = tmp_path / "runtime.password"

    real_open = _os.open
    racing_value = "racing-worker-secret"

    def racing_open(path, flags, mode=0o777, **kwargs):
        if str(path) == str(target) and flags & _os.O_EXCL:
            # Another worker won the race in between: create the file now.
            target.write_text(racing_value)
            target.chmod(0o600)
        return real_open(path, flags, mode, **kwargs)

    import plugin.services.runtime_password as mod

    monkey_state = mod.os.open  # capture so the test cleans up
    mod.os.open = racing_open
    try:
        result = load_or_create_password(tmp_path)
    finally:
        mod.os.open = monkey_state

    assert result == racing_value
