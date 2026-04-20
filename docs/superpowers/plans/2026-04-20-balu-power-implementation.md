# BaluPower — Intelligent GPU Power Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a standalone systemd-managed daemon `balu-power` that arbitrates AMD RX 7900 XT (RDNA3) GPU power profiles (`gaming`, `compute`, `display-off`, `llm-idle`, `idle`) across three trigger clients (GameMode hook, Ollama-watcher, display-watcher). Push-only protocol, TTL+priority resolution, yaml-overridable, systemd-hardened.

**Architecture:** Root daemon owns a Unix socket (`/run/balu-power.sock`, group `balu-power`, 0660) and a claim registry. Clients send NDJSON `claim`/`release`/`status`/`reload` messages. On every registry mutation the reconciler computes `max(priority)` and writes sysfs only on delta. Non-root clients: `balu-powerctl` CLI (manual), user-session systemd units `balu-power-ollama-watcher` (polls Ollama `/api/ps`) and `balu-power-display-watcher` (subscribes `org.freedesktop.login1.Session.IdleHint`). GameMode custom hook invokes the CLI. Empty registry implicitly falls back to `idle`.

**Tech Stack:** Python 3.12+, `asyncio`, `pyyaml`, `httpx` (ollama-watcher), `dbus-next` (display-watcher), pytest + `python-dbusmock` for tests, `uv` workspace, systemd unit files.

**Parent spec:** [`docs/superpowers/specs/2026-04-20-balu-power-design.md`](../specs/2026-04-20-balu-power-design.md)

---

## File Structure

```
Balu_Code/
├── pyproject.toml                                         [mod: add power/tests to testpaths]
├── power/                                                 [new package, installable separately]
│   ├── pyproject.toml                                     [new Task 1]
│   ├── balu_power/
│   │   ├── __init__.py                                    [new Task 1]
│   │   ├── __main__.py                                    [new Task 9]
│   │   ├── profiles.py                                    [new Tasks 2-3]
│   │   ├── protocol.py                                    [new Task 4]
│   │   ├── registry.py                                    [new Task 5]
│   │   ├── hw_detect.py                                   [new Task 6]
│   │   ├── gpu_driver.py                                  [new Task 7]
│   │   └── daemon.py                                      [new Tasks 8-9]
│   ├── balu_powerctl/
│   │   ├── __init__.py                                    [new Task 10]
│   │   └── __main__.py                                    [new Task 10]
│   ├── watchers/
│   │   ├── __init__.py                                    [new Task 11]
│   │   ├── ollama_watcher.py                              [new Task 11]
│   │   └── display_watcher.py                             [new Task 12]
│   ├── contrib/
│   │   ├── gamemode-hook.ini                              [new Task 13]
│   │   ├── safe-defaults.conf                             [new Task 13]
│   │   ├── balu-power-reset                               [new Task 13]
│   │   ├── install.sh                                     [new Task 14]
│   │   └── systemd/
│   │       ├── balu-power.service                         [new Task 13]
│   │       ├── balu-power-ollama-watcher.service          [new Task 13]
│   │       └── balu-power-display-watcher.service         [new Task 13]
│   └── tests/
│       ├── __init__.py                                    [new Task 1]
│       ├── conftest.py                                    [new Task 1]
│       ├── unit/
│       │   ├── __init__.py                                [new Task 1]
│       │   ├── test_profiles.py                           [new Tasks 2-3]
│       │   ├── test_protocol.py                           [new Task 4]
│       │   ├── test_registry.py                           [new Task 5]
│       │   ├── test_hw_detect.py                          [new Task 6]
│       │   └── test_gpu_driver.py                         [new Task 7]
│       ├── integration/
│       │   ├── __init__.py                                [new Task 1]
│       │   ├── test_daemon_roundtrip.py                   [new Task 8]
│       │   ├── test_ollama_watcher.py                     [new Task 11]
│       │   └── test_display_watcher.py                    [new Task 12]
│       └── live/
│           └── verify_7900xt.sh                           [new Task 15]
└── docs/
    ├── power/
    │   ├── setup.md                                       [new Task 14]
    │   ├── configuration.md                               [new Task 14]
    │   └── clients.md                                     [new Task 14]
    └── power-phase-1-verification.md                      [new Task 15]
```

Task 16 is end-of-phase verification.

---

## Task 1: Scaffold `power/` sub-package

Bring up the package skeleton and wire it into the workspace pytest config. After this task, `pytest power/tests` runs (zero tests) and `python -c "import balu_power"` works.

**Files:**
- Create: `power/pyproject.toml`
- Create: `power/balu_power/__init__.py`
- Create: `power/tests/__init__.py`
- Create: `power/tests/unit/__init__.py`
- Create: `power/tests/integration/__init__.py`
- Create: `power/tests/conftest.py`
- Modify: `pyproject.toml` (root) — add `power/tests` to `testpaths`

- [ ] **Step 1: Create `power/pyproject.toml`**

```toml
[project]
name = "balu-power"
version = "0.1.0"
description = "Intelligent GPU power management daemon for AMD RDNA3 on Linux."
requires-python = ">=3.12"
dependencies = [
  "pyyaml>=6.0",
  "httpx>=0.27",
  "dbus-next>=0.2.3",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "python-dbusmock>=0.31",
]

[project.scripts]
balu-power = "balu_power.__main__:main"
balu-powerctl = "balu_powerctl.__main__:main"
balu-power-ollama-watcher = "watchers.ollama_watcher:main"
balu-power-display-watcher = "watchers.display_watcher:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["balu_power*", "balu_powerctl*", "watchers*"]
```

- [ ] **Step 2: Create empty package files**

```bash
mkdir -p power/balu_power power/balu_powerctl power/watchers
mkdir -p power/tests/unit power/tests/integration power/tests/live
touch power/balu_power/__init__.py
touch power/tests/__init__.py
touch power/tests/unit/__init__.py
touch power/tests/integration/__init__.py
```

- [ ] **Step 3: Create `power/tests/conftest.py`** with shared sysfs-mock fixture

```python
"""Shared pytest fixtures for balu-power tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def mock_sysfs(tmp_path: Path) -> Path:
    """Build a fake /sys/class/drm/card0 tree writable by the test."""
    card = tmp_path / "sys" / "class" / "drm" / "card0"
    device = card / "device"
    device.mkdir(parents=True)

    (device / "vendor").write_text("0x1002\n")            # AMD
    (device / "device").write_text("0x744c\n")            # RX 7900 XTX id; 7900 XT is 0x7448
    (device / "power_dpm_force_performance_level").write_text("auto\n")
    (device / "pp_power_profile_mode").write_text("0\n")
    (device / "gpu_busy_percent").write_text("0\n")

    hwmon = device / "hwmon" / "hwmon0"
    hwmon.mkdir(parents=True)
    (hwmon / "name").write_text("amdgpu\n")
    (hwmon / "power1_cap").write_text("315000000\n")
    (hwmon / "power1_cap_max").write_text("357000000\n")
    (hwmon / "power1_cap_min").write_text("1000000\n")

    return tmp_path / "sys"
```

- [ ] **Step 4: Append to `pyproject.toml` (root) testpaths**

Current (line 17): `testpaths = ["shared/tests", "plugin/tests", "cli/tests", "scripts/tests"]`

Change to:
```toml
testpaths = ["shared/tests", "plugin/tests", "cli/tests", "scripts/tests", "power/tests"]
```

- [ ] **Step 5: Install deps and verify pytest collection**

```bash
cd /home/sven/projects/plugins/Balu_Code
uv pip install -e power[dev]
.venv/bin/pytest power/tests --collect-only
```

Expected: `collected 0 items` (no tests yet), no import errors.

- [ ] **Step 6: Commit**

```bash
git add power/ pyproject.toml
git commit -m "feat(power): scaffold balu-power sub-package with empty pytest tree"
```

---

## Task 2: `profiles.py` — data types + hardcoded defaults

Pure value objects describing a profile and the full profile catalog. No yaml yet — yaml loader is Task 3. TDD-first.

**Files:**
- Create: `power/balu_power/profiles.py`
- Create: `power/tests/unit/test_profiles.py`

- [ ] **Step 1: Write failing test** — `power/tests/unit/test_profiles.py`

```python
from balu_power.profiles import (
    DEFAULT_PROFILES,
    DEFAULT_PRIORITY,
    Profile,
    profile_by_name,
)


def test_default_profile_catalog_has_five_states():
    names = {p.name for p in DEFAULT_PROFILES}
    assert names == {"gaming", "compute", "display-off", "llm-idle", "idle"}


def test_profile_gaming_uses_3d_full_screen_mode():
    p = profile_by_name(DEFAULT_PROFILES, "gaming")
    assert p.performance_level == "auto"
    assert p.power_profile_mode == 1
    assert p.power_cap_w is None


def test_profile_compute_uses_compute_mode():
    p = profile_by_name(DEFAULT_PROFILES, "compute")
    assert p.power_profile_mode == 4


def test_profile_display_off_uses_low_level():
    p = profile_by_name(DEFAULT_PROFILES, "display-off")
    assert p.performance_level == "low"
    assert p.power_profile_mode == 5


def test_profile_idle_is_fallback_default():
    p = profile_by_name(DEFAULT_PROFILES, "idle")
    assert p.performance_level == "auto"
    assert p.power_profile_mode == 5


def test_default_priority_order_low_to_high():
    assert DEFAULT_PRIORITY == ["idle", "llm-idle", "display-off", "compute", "gaming"]


def test_profile_immutable():
    p = profile_by_name(DEFAULT_PROFILES, "idle")
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.power_profile_mode = 99


import pytest  # noqa: E402  (imports out of order kept so pytest symbol is near its only use)
```

- [ ] **Step 2: Run test, verify it fails**

```bash
.venv/bin/pytest power/tests/unit/test_profiles.py -v
```

Expected: `ModuleNotFoundError: No module named 'balu_power.profiles'`.

- [ ] **Step 3: Implement `power/balu_power/profiles.py`**

```python
"""Profile value objects and hardcoded defaults.

A profile maps to a single GPU power state. Multiple profiles can be active
in the registry simultaneously; the reconciler picks the one with highest
priority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Profile:
    """A single GPU power state."""

    name: str
    performance_level: str       # "auto" | "low" | "high" | "manual" | "profile_*"
    power_profile_mode: int      # matches sysfs pp_power_profile_mode index
    power_cap_w: int | None      # None → do not touch power1_cap
    ollama_unload: bool = False  # if True and profile is llm-idle: watcher unloads ollama model


# Defaults tuned for AMD RX 7900 XT/XTX (RDNA3). Overridable via
# /etc/balu-power/profiles.yaml. See docs/power/configuration.md.
DEFAULT_PROFILES: tuple[Profile, ...] = (
    Profile("gaming", "auto", 1, None),         # 3D_FULL_SCREEN
    Profile("compute", "auto", 4, None),        # COMPUTE
    Profile("display-off", "low", 5, None),     # POWER_SAVING + low level
    Profile("llm-idle", "auto", 5, None),       # POWER_SAVING, auto level (ollama_unload=False)
    Profile("idle", "auto", 5, None),           # fallback
)

# low → high. The reconciler picks max() by index in this list.
DEFAULT_PRIORITY: list[str] = ["idle", "llm-idle", "display-off", "compute", "gaming"]


def profile_by_name(profiles: Iterable[Profile], name: str) -> Profile:
    for p in profiles:
        if p.name == name:
            return p
    raise KeyError(name)
```

- [ ] **Step 4: Run test, verify it passes**

```bash
.venv/bin/pytest power/tests/unit/test_profiles.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add power/balu_power/profiles.py power/tests/unit/test_profiles.py
git commit -m "feat(power): add Profile dataclass and default RDNA3 catalog"
```

---

## Task 3: `profiles.py` — YAML loader + safe-defaults guard

Load `/etc/balu-power/profiles.yaml` over the hardcoded defaults, merge, validate against safe-defaults. Reject configs that could exceed the hardcoded `max_power_cap_w`.

**Files:**
- Modify: `power/balu_power/profiles.py`
- Modify: `power/tests/unit/test_profiles.py`

- [ ] **Step 1: Add failing tests** — append to `power/tests/unit/test_profiles.py`

```python
from pathlib import Path

from balu_power.profiles import ProfileConfigError, load_profiles


def test_load_profiles_no_yaml_returns_defaults(tmp_path: Path):
    cfg = load_profiles(tmp_path / "nonexistent.yaml")
    assert [p.name for p in cfg.profiles] == [p.name for p in DEFAULT_PROFILES]
    assert cfg.priority == DEFAULT_PRIORITY
    assert cfg.card == "card0"


def test_load_profiles_yaml_overrides_fields(tmp_path: Path):
    yaml_file = tmp_path / "profiles.yaml"
    yaml_file.write_text(
        "profiles:\n"
        "  gaming:\n"
        "    performance_level: auto\n"
        "    power_profile_mode: 1\n"
        "    power_cap_w: 280\n"
        "card: card1\n"
    )
    cfg = load_profiles(yaml_file)
    gaming = profile_by_name(cfg.profiles, "gaming")
    assert gaming.power_cap_w == 280
    assert cfg.card == "card1"
    # Unchanged profiles keep defaults.
    idle = profile_by_name(cfg.profiles, "idle")
    assert idle.power_profile_mode == 5


def test_load_profiles_rejects_cap_over_safe_limit(tmp_path: Path):
    yaml_file = tmp_path / "profiles.yaml"
    yaml_file.write_text(
        "profiles:\n"
        "  gaming:\n"
        "    power_cap_w: 500\n"
    )
    with pytest.raises(ProfileConfigError, match="exceeds max_power_cap_w"):
        load_profiles(yaml_file)


def test_load_profiles_rejects_unknown_performance_level(tmp_path: Path):
    yaml_file = tmp_path / "profiles.yaml"
    yaml_file.write_text(
        "profiles:\n"
        "  gaming:\n"
        "    performance_level: turbo\n"
    )
    with pytest.raises(ProfileConfigError, match="invalid performance_level"):
        load_profiles(yaml_file)


def test_load_profiles_rejects_unknown_profile_name(tmp_path: Path):
    yaml_file = tmp_path / "profiles.yaml"
    yaml_file.write_text(
        "profiles:\n"
        "  turbo:\n"
        "    performance_level: high\n"
    )
    with pytest.raises(ProfileConfigError, match="unknown profile 'turbo'"):
        load_profiles(yaml_file)


def test_load_profiles_rejects_priority_with_missing_profile(tmp_path: Path):
    yaml_file = tmp_path / "profiles.yaml"
    yaml_file.write_text(
        "priority: [idle, gaming]\n"  # missing compute/display-off/llm-idle
    )
    with pytest.raises(ProfileConfigError, match="priority must list all"):
        load_profiles(yaml_file)


def test_load_profiles_accepts_ollama_unload_flag(tmp_path: Path):
    yaml_file = tmp_path / "profiles.yaml"
    yaml_file.write_text(
        "profiles:\n"
        "  llm-idle:\n"
        "    ollama_unload: true\n"
    )
    cfg = load_profiles(yaml_file)
    llm = profile_by_name(cfg.profiles, "llm-idle")
    assert llm.ollama_unload is True
    # Default profile still False.
    gaming = profile_by_name(cfg.profiles, "gaming")
    assert gaming.ollama_unload is False


def test_load_profiles_rejects_non_bool_ollama_unload(tmp_path: Path):
    yaml_file = tmp_path / "profiles.yaml"
    yaml_file.write_text(
        "profiles:\n"
        "  llm-idle:\n"
        "    ollama_unload: yes_please\n"
    )
    with pytest.raises(ProfileConfigError, match="ollama_unload must be bool"):
        load_profiles(yaml_file)
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
.venv/bin/pytest power/tests/unit/test_profiles.py -v
```

Expected: 6 failures with `ImportError: cannot import name 'ProfileConfigError'`.

- [ ] **Step 3: Extend `power/balu_power/profiles.py`**

Append below the existing code:

```python
import dataclasses
from pathlib import Path

import yaml


# Non-overridable bounds. Mirror /etc/balu-power/safe-defaults.conf.
MAX_POWER_CAP_W: int = 400
VALID_PERFORMANCE_LEVELS: frozenset[str] = frozenset({
    "auto", "low", "high",
    "profile_standard", "profile_min_sclk", "profile_min_mclk", "profile_peak",
})


class ProfileConfigError(ValueError):
    """Raised when user-supplied profiles.yaml is invalid or exceeds safe bounds."""


@dataclasses.dataclass(frozen=True)
class ProfileConfig:
    profiles: tuple[Profile, ...]
    priority: list[str]
    card: str


def load_profiles(path: Path) -> ProfileConfig:
    """Load /etc/balu-power/profiles.yaml over hardcoded defaults.

    Missing file → defaults. Invalid file → ProfileConfigError.
    """
    if not path.exists():
        return ProfileConfig(
            profiles=DEFAULT_PROFILES,
            priority=list(DEFAULT_PRIORITY),
            card="card0",
        )

    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ProfileConfigError(f"{path}: top-level must be a mapping")

    profile_overrides = raw.get("profiles") or {}
    if not isinstance(profile_overrides, dict):
        raise ProfileConfigError(f"{path}: 'profiles' must be a mapping")

    default_names = {p.name for p in DEFAULT_PROFILES}
    merged: list[Profile] = []
    for default in DEFAULT_PROFILES:
        override = profile_overrides.get(default.name, {})
        merged.append(_merge_profile(default, override))

    for name in profile_overrides:
        if name not in default_names:
            raise ProfileConfigError(f"unknown profile '{name}' in {path}")

    priority = raw.get("priority") or list(DEFAULT_PRIORITY)
    if set(priority) != default_names:
        raise ProfileConfigError(
            f"priority must list all five profiles; got {priority}"
        )

    card = raw.get("card") or "card0"
    if not isinstance(card, str):
        raise ProfileConfigError(f"{path}: 'card' must be a string")

    return ProfileConfig(profiles=tuple(merged), priority=list(priority), card=card)


def _merge_profile(default: Profile, override: dict) -> Profile:
    if not isinstance(override, dict):
        raise ProfileConfigError(f"profile {default.name!r}: override must be mapping")

    level = override.get("performance_level", default.performance_level)
    mode = override.get("power_profile_mode", default.power_profile_mode)
    cap = override.get("power_cap_w", default.power_cap_w)
    ollama_unload = override.get("ollama_unload", default.ollama_unload)

    if level not in VALID_PERFORMANCE_LEVELS:
        raise ProfileConfigError(
            f"profile {default.name!r}: invalid performance_level {level!r}"
        )
    if not isinstance(mode, int) or mode < 0:
        raise ProfileConfigError(
            f"profile {default.name!r}: power_profile_mode must be int >= 0"
        )
    if cap is not None:
        if not isinstance(cap, int) or cap <= 0:
            raise ProfileConfigError(
                f"profile {default.name!r}: power_cap_w must be positive int or omitted"
            )
        if cap > MAX_POWER_CAP_W:
            raise ProfileConfigError(
                f"profile {default.name!r}: power_cap_w {cap} exceeds max_power_cap_w {MAX_POWER_CAP_W}"
            )
    if not isinstance(ollama_unload, bool):
        raise ProfileConfigError(
            f"profile {default.name!r}: ollama_unload must be bool"
        )

    return Profile(
        name=default.name,
        performance_level=level,
        power_profile_mode=mode,
        power_cap_w=cap,
        ollama_unload=ollama_unload,
    )
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
.venv/bin/pytest power/tests/unit/test_profiles.py -v
```

Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add power/balu_power/profiles.py power/tests/unit/test_profiles.py
git commit -m "feat(power): add profiles.yaml loader with safe-defaults guard"
```

---

## Task 4: `protocol.py` — NDJSON request/response

Pure parsing of the wire format. No I/O — just bytes ↔ dataclasses with validation. Errors are returned as structured response objects, not raised.

**Files:**
- Create: `power/balu_power/protocol.py`
- Create: `power/tests/unit/test_protocol.py`

- [ ] **Step 1: Write failing tests** — `power/tests/unit/test_protocol.py`

```python
import json

import pytest

from balu_power.protocol import (
    ClaimRequest,
    ReleaseRequest,
    ReloadRequest,
    Response,
    StatusRequest,
    parse_request,
    serialize_response,
)


def test_parse_claim_ok():
    line = b'{"v":1,"op":"claim","client_id":"x","state":"compute","ttl_seconds":15}\n'
    req = parse_request(line)
    assert isinstance(req, ClaimRequest)
    assert req.client_id == "x"
    assert req.state == "compute"
    assert req.ttl_seconds == 15


def test_parse_claim_ttl_null_means_infinite():
    line = b'{"v":1,"op":"claim","client_id":"x","state":"gaming","ttl_seconds":null}'
    req = parse_request(line)
    assert isinstance(req, ClaimRequest)
    assert req.ttl_seconds is None


def test_parse_release_ok():
    line = b'{"v":1,"op":"release","client_id":"x"}'
    req = parse_request(line)
    assert isinstance(req, ReleaseRequest)
    assert req.client_id == "x"


def test_parse_status():
    line = b'{"v":1,"op":"status"}'
    assert isinstance(parse_request(line), StatusRequest)


def test_parse_reload():
    line = b'{"v":1,"op":"reload"}'
    assert isinstance(parse_request(line), ReloadRequest)


def test_parse_rejects_invalid_json():
    with pytest.raises(ValueError, match="parse_error"):
        parse_request(b'not json')


def test_parse_rejects_unknown_op():
    with pytest.raises(ValueError, match="unknown_op"):
        parse_request(b'{"v":1,"op":"detonate"}')


def test_parse_rejects_missing_client_id_on_claim():
    with pytest.raises(ValueError, match="missing_field"):
        parse_request(b'{"v":1,"op":"claim","state":"idle","ttl_seconds":1}')


def test_parse_rejects_ttl_zero():
    with pytest.raises(ValueError, match="invalid_ttl"):
        parse_request(
            b'{"v":1,"op":"claim","client_id":"x","state":"idle","ttl_seconds":0}'
        )


def test_parse_rejects_ttl_negative():
    with pytest.raises(ValueError, match="invalid_ttl"):
        parse_request(
            b'{"v":1,"op":"claim","client_id":"x","state":"idle","ttl_seconds":-5}'
        )


def test_parse_rejects_oversized_line():
    line = b'{"v":1,"op":"claim","client_id":"' + b"a" * 4100 + b'","state":"idle","ttl_seconds":1}'
    with pytest.raises(ValueError, match="line_too_long"):
        parse_request(line)


def test_serialize_ok_response():
    out = serialize_response(Response.success())
    assert json.loads(out.rstrip()) == {"ok": True}
    assert out.endswith(b"\n")


def test_serialize_error_response():
    out = serialize_response(Response.failure("unknown_state", "state 'turbo'"))
    assert json.loads(out.rstrip()) == {
        "ok": False,
        "error": "unknown_state",
        "message": "state 'turbo'",
    }


def test_serialize_status_payload():
    out = serialize_response(
        Response.status(
            current_state="compute",
            claims=[{"client_id": "x", "state": "compute", "expires_in_s": 10}],
        )
    )
    decoded = json.loads(out)
    assert decoded["ok"] is True
    assert decoded["current_state"] == "compute"
    assert decoded["claims"][0]["client_id"] == "x"
```

- [ ] **Step 2: Run tests, verify all fail**

```bash
.venv/bin/pytest power/tests/unit/test_protocol.py -v
```

Expected: `ModuleNotFoundError: No module named 'balu_power.protocol'`.

- [ ] **Step 3: Implement `power/balu_power/protocol.py`**

```python
"""NDJSON wire protocol for the balu-power socket.

One request per line. Requests are dataclasses; responses are built via
``Response`` factory methods. Parsing is pure: no I/O, no side effects.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any

MAX_LINE_BYTES = 4096


@dataclass(frozen=True)
class ClaimRequest:
    client_id: str
    state: str
    ttl_seconds: int | None  # None = infinite until release


@dataclass(frozen=True)
class ReleaseRequest:
    client_id: str


@dataclass(frozen=True)
class StatusRequest:
    pass


@dataclass(frozen=True)
class ReloadRequest:
    pass


Request = ClaimRequest | ReleaseRequest | StatusRequest | ReloadRequest


@dataclass(frozen=True)
class Response:
    ok: bool
    error: str | None = None
    message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls) -> "Response":
        return cls(ok=True)

    @classmethod
    def failure(cls, error: str, message: str) -> "Response":
        return cls(ok=False, error=error, message=message)

    @classmethod
    def status(cls, current_state: str, claims: list[dict[str, Any]]) -> "Response":
        return cls(
            ok=True,
            payload={"current_state": current_state, "claims": claims},
        )


def parse_request(line: bytes) -> Request:
    if len(line) > MAX_LINE_BYTES:
        raise ValueError("line_too_long")
    try:
        data = json.loads(line.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"parse_error: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("parse_error: top-level must be object")

    op = data.get("op")
    if op == "claim":
        return _parse_claim(data)
    if op == "release":
        return _parse_release(data)
    if op == "status":
        return StatusRequest()
    if op == "reload":
        return ReloadRequest()
    raise ValueError(f"unknown_op: {op!r}")


def _parse_claim(data: dict[str, Any]) -> ClaimRequest:
    for field_ in ("client_id", "state", "ttl_seconds"):
        if field_ not in data:
            raise ValueError(f"missing_field: {field_}")
    client_id = data["client_id"]
    state = data["state"]
    ttl = data["ttl_seconds"]
    if not isinstance(client_id, str) or not client_id:
        raise ValueError("missing_field: client_id must be non-empty string")
    if not isinstance(state, str) or not state:
        raise ValueError("missing_field: state must be non-empty string")
    if ttl is not None:
        if not isinstance(ttl, int) or ttl <= 0:
            raise ValueError(f"invalid_ttl: {ttl!r}")
    return ClaimRequest(client_id=client_id, state=state, ttl_seconds=ttl)


def _parse_release(data: dict[str, Any]) -> ReleaseRequest:
    if "client_id" not in data:
        raise ValueError("missing_field: client_id")
    client_id = data["client_id"]
    if not isinstance(client_id, str) or not client_id:
        raise ValueError("missing_field: client_id must be non-empty string")
    return ReleaseRequest(client_id=client_id)


def serialize_response(resp: Response) -> bytes:
    body: dict[str, Any] = {"ok": resp.ok}
    if not resp.ok:
        body["error"] = resp.error
        body["message"] = resp.message
    body.update(resp.payload)
    return (json.dumps(body, separators=(",", ":")) + "\n").encode("utf-8")
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
.venv/bin/pytest power/tests/unit/test_protocol.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add power/balu_power/protocol.py power/tests/unit/test_protocol.py
git commit -m "feat(power): add NDJSON protocol parser with validation"
```

---

## Task 5: `registry.py` — Claim store + priority resolution

The heart of the daemon's logic. Pure in-memory state, time-source injectable for tests.

**Files:**
- Create: `power/balu_power/registry.py`
- Create: `power/tests/unit/test_registry.py`

- [ ] **Step 1: Write failing tests** — `power/tests/unit/test_registry.py`

```python
from balu_power.registry import ClaimRegistry


def test_empty_registry_resolves_to_idle():
    reg = ClaimRegistry(priority=["idle", "llm-idle", "display-off", "compute", "gaming"])
    assert reg.resolve(now=100.0) == "idle"


def test_single_claim_wins():
    reg = ClaimRegistry(priority=["idle", "llm-idle", "display-off", "compute", "gaming"])
    reg.claim("ollama-watcher", "compute", ttl_seconds=15, now=100.0)
    assert reg.resolve(now=100.0) == "compute"


def test_higher_priority_wins_regardless_of_order():
    reg = ClaimRegistry(priority=["idle", "llm-idle", "display-off", "compute", "gaming"])
    reg.claim("display-watcher", "display-off", ttl_seconds=None, now=100.0)
    reg.claim("ollama-watcher", "compute", ttl_seconds=15, now=100.0)
    assert reg.resolve(now=100.0) == "compute"


def test_expired_claim_is_ignored():
    reg = ClaimRegistry(priority=["idle", "llm-idle", "display-off", "compute", "gaming"])
    reg.claim("ollama-watcher", "compute", ttl_seconds=10, now=100.0)
    assert reg.resolve(now=109.9) == "compute"
    assert reg.resolve(now=110.1) == "idle"


def test_null_ttl_never_expires():
    reg = ClaimRegistry(priority=["idle", "llm-idle", "display-off", "compute", "gaming"])
    reg.claim("gamemode", "gaming", ttl_seconds=None, now=100.0)
    assert reg.resolve(now=100_000.0) == "gaming"


def test_duplicate_client_id_replaces_prior_claim():
    reg = ClaimRegistry(priority=["idle", "llm-idle", "display-off", "compute", "gaming"])
    reg.claim("x", "gaming", ttl_seconds=None, now=100.0)
    reg.claim("x", "idle", ttl_seconds=5, now=100.0)
    assert reg.resolve(now=100.0) == "idle"
    # and only one claim from client "x"
    assert len(reg.snapshot(now=100.0)) == 1


def test_release_removes_claim():
    reg = ClaimRegistry(priority=["idle", "llm-idle", "display-off", "compute", "gaming"])
    reg.claim("gamemode", "gaming", ttl_seconds=None, now=100.0)
    reg.release("gamemode")
    assert reg.resolve(now=100.0) == "idle"


def test_release_unknown_client_is_noop():
    reg = ClaimRegistry(priority=["idle", "llm-idle", "display-off", "compute", "gaming"])
    reg.release("ghost")  # does not raise
    assert reg.resolve(now=100.0) == "idle"


def test_snapshot_omits_expired():
    reg = ClaimRegistry(priority=["idle", "llm-idle", "display-off", "compute", "gaming"])
    reg.claim("a", "compute", ttl_seconds=10, now=100.0)
    reg.claim("b", "display-off", ttl_seconds=None, now=100.0)
    snap = reg.snapshot(now=200.0)
    assert len(snap) == 1
    assert snap[0]["client_id"] == "b"
    assert snap[0]["expires_in_s"] is None


def test_snapshot_reports_remaining_ttl():
    reg = ClaimRegistry(priority=["idle", "llm-idle", "display-off", "compute", "gaming"])
    reg.claim("a", "compute", ttl_seconds=15, now=100.0)
    snap = reg.snapshot(now=105.0)
    assert snap[0]["expires_in_s"] == 10
```

- [ ] **Step 2: Run tests, verify all fail**

Expected: `ModuleNotFoundError: No module named 'balu_power.registry'`.

- [ ] **Step 3: Implement `power/balu_power/registry.py`**

```python
"""In-memory claim store with TTL and priority resolution.

The registry is pure state — no I/O, no timers. The daemon calls
``resolve(now=...)`` on each event (claim/release/tick) and writes sysfs
only if the result differs from the last-written profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class _Claim:
    client_id: str
    state: str
    expires_at: float | None  # None = never expires


class ClaimRegistry:
    """Map of client_id → active claim. Replace-semantics on duplicate client_id."""

    def __init__(self, priority: list[str]) -> None:
        self._priority = priority
        self._claims: dict[str, _Claim] = {}

    def claim(
        self,
        client_id: str,
        state: str,
        ttl_seconds: int | None,
        now: float,
    ) -> None:
        expires_at = None if ttl_seconds is None else now + ttl_seconds
        self._claims[client_id] = _Claim(client_id, state, expires_at)

    def release(self, client_id: str) -> None:
        self._claims.pop(client_id, None)

    def resolve(self, now: float) -> str:
        """Return the highest-priority unexpired state. Empty → first priority entry (`idle`)."""
        active = [c for c in self._claims.values() if not self._is_expired(c, now)]
        if not active:
            return self._priority[0]  # "idle"
        return max(active, key=lambda c: self._priority_index(c.state)).state

    def snapshot(self, now: float) -> list[dict[str, Any]]:
        """List of unexpired claims for the status response."""
        out: list[dict[str, Any]] = []
        for c in self._claims.values():
            if self._is_expired(c, now):
                continue
            expires_in = None if c.expires_at is None else max(0, int(c.expires_at - now))
            out.append({
                "client_id": c.client_id,
                "state": c.state,
                "expires_in_s": expires_in,
            })
        return out

    def purge_expired(self, now: float) -> None:
        self._claims = {
            cid: c for cid, c in self._claims.items() if not self._is_expired(c, now)
        }

    def _is_expired(self, c: _Claim, now: float) -> bool:
        return c.expires_at is not None and c.expires_at <= now

    def _priority_index(self, state: str) -> int:
        try:
            return self._priority.index(state)
        except ValueError:
            return -1  # unknown state ranks below everything
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
.venv/bin/pytest power/tests/unit/test_registry.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add power/balu_power/registry.py power/tests/unit/test_registry.py
git commit -m "feat(power): add ClaimRegistry with TTL and priority resolution"
```

---

## Task 6: `hw_detect.py` — card detection

Walk `/sys/class/drm/card*/device/` and pick the first AMD device. yaml-config override wins. Unknown vendor → raise; unknown AMD device ID → WARN but proceed.

**Files:**
- Create: `power/balu_power/hw_detect.py`
- Create: `power/tests/unit/test_hw_detect.py`

- [ ] **Step 1: Write failing tests** — `power/tests/unit/test_hw_detect.py`

```python
from pathlib import Path

import pytest

from balu_power.hw_detect import HardwareError, detect_card


def test_detect_finds_amd_card(mock_sysfs: Path):
    result = detect_card(sys_root=mock_sysfs, preferred_card=None)
    assert result.card == "card0"
    assert result.drm_path == mock_sysfs / "class" / "drm" / "card0"
    assert result.is_known_rdna3 is True    # 0x744c is in the allowlist
    assert result.is_amd is True


def test_detect_respects_preferred_card(tmp_path: Path, mock_sysfs: Path):
    # Preferred card that doesn't exist → error
    with pytest.raises(HardwareError, match="preferred card 'card9' not found"):
        detect_card(sys_root=mock_sysfs, preferred_card="card9")


def test_detect_unknown_amd_id_succeeds_with_warning(tmp_path: Path):
    # Build a sysfs with an unknown AMD device id.
    card = tmp_path / "sys" / "class" / "drm" / "card0"
    device = card / "device"
    device.mkdir(parents=True)
    (device / "vendor").write_text("0x1002\n")
    (device / "device").write_text("0xdead\n")
    result = detect_card(sys_root=tmp_path / "sys", preferred_card=None)
    assert result.is_amd is True
    assert result.is_known_rdna3 is False


def test_detect_errors_when_no_amd_card(tmp_path: Path):
    card = tmp_path / "sys" / "class" / "drm" / "card0"
    device = card / "device"
    device.mkdir(parents=True)
    (device / "vendor").write_text("0x10de\n")      # NVIDIA
    (device / "device").write_text("0x2684\n")
    with pytest.raises(HardwareError, match="no AMD GPU found"):
        detect_card(sys_root=tmp_path / "sys", preferred_card=None)


def test_detect_errors_when_sys_root_missing(tmp_path: Path):
    with pytest.raises(HardwareError, match="drm root not found"):
        detect_card(sys_root=tmp_path / "nope", preferred_card=None)
```

- [ ] **Step 2: Run tests, verify all fail**

Expected: `ModuleNotFoundError: No module named 'balu_power.hw_detect'`.

- [ ] **Step 3: Implement `power/balu_power/hw_detect.py`**

```python
"""Detect the AMD GPU to manage.

v1 targets RDNA3. Unknown AMD device IDs still work (generic sysfs paths)
but emit a WARN at daemon startup.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

AMD_VENDOR_ID = "0x1002"

# PCI device IDs for RDNA3 consumer cards. Extend conservatively.
KNOWN_RDNA3_IDS: frozenset[str] = frozenset({
    "0x7448",   # RX 7900 XT
    "0x744c",   # RX 7900 XTX / 7900 GRE
    "0x747e",   # RX 7800 XT / 7700 XT
    "0x7480",   # RX 7600
})


class HardwareError(RuntimeError):
    """Raised when no suitable AMD GPU is found."""


@dataclass(frozen=True)
class DetectedCard:
    card: str                # "card0"
    drm_path: Path           # /sys/class/drm/card0
    device_path: Path        # /sys/class/drm/card0/device
    vendor_id: str           # "0x1002"
    device_id: str           # "0x744c"
    is_amd: bool
    is_known_rdna3: bool


def detect_card(*, sys_root: Path, preferred_card: str | None) -> DetectedCard:
    drm_root = sys_root / "class" / "drm"
    if not drm_root.exists():
        raise HardwareError(f"drm root not found: {drm_root}")

    candidates: list[Path] = []
    if preferred_card is not None:
        candidate = drm_root / preferred_card
        if not candidate.is_dir():
            raise HardwareError(f"preferred card '{preferred_card}' not found")
        candidates.append(candidate)
    else:
        # card0, card1, ... sorted
        candidates = sorted(
            p for p in drm_root.iterdir()
            if p.name.startswith("card") and "-" not in p.name and p.is_dir()
        )

    for candidate in candidates:
        device = candidate / "device"
        vendor_file = device / "vendor"
        device_file = device / "device"
        if not (vendor_file.exists() and device_file.exists()):
            continue
        vendor = vendor_file.read_text().strip()
        device_id = device_file.read_text().strip()
        if vendor != AMD_VENDOR_ID:
            continue
        is_known = device_id in KNOWN_RDNA3_IDS
        if not is_known:
            _log.warning(
                "untested AMD device id %s on %s; proceeding with generic sysfs paths",
                device_id, candidate.name,
            )
        return DetectedCard(
            card=candidate.name,
            drm_path=candidate,
            device_path=device,
            vendor_id=vendor,
            device_id=device_id,
            is_amd=True,
            is_known_rdna3=is_known,
        )

    raise HardwareError("no AMD GPU found in drm tree")
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
.venv/bin/pytest power/tests/unit/test_hw_detect.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add power/balu_power/hw_detect.py power/tests/unit/test_hw_detect.py
git commit -m "feat(power): add AMD RDNA3 card detection with yaml override"
```

---

## Task 7: `gpu_driver.py` — idempotent sysfs writer

Writes a `Profile` to sysfs for a `DetectedCard`. Remembers the last-applied profile in-memory; no-ops when the same profile is reapplied. Graceful on `OSError` (logs WARN, leaves last-good state untouched). `reset_to_defaults()` for the `ExecStopPost` hook.

**Files:**
- Create: `power/balu_power/gpu_driver.py`
- Create: `power/tests/unit/test_gpu_driver.py`

- [ ] **Step 1: Write failing tests** — `power/tests/unit/test_gpu_driver.py`

```python
from pathlib import Path

import pytest

from balu_power.gpu_driver import GpuDriver
from balu_power.hw_detect import DetectedCard
from balu_power.profiles import Profile


@pytest.fixture
def card(mock_sysfs: Path) -> DetectedCard:
    drm = mock_sysfs / "class" / "drm" / "card0"
    return DetectedCard(
        card="card0",
        drm_path=drm,
        device_path=drm / "device",
        vendor_id="0x1002",
        device_id="0x744c",
        is_amd=True,
        is_known_rdna3=True,
    )


def test_apply_writes_performance_level_and_profile_mode(card: DetectedCard):
    drv = GpuDriver(card=card)
    drv.apply(Profile("compute", "auto", 4, None))
    assert (card.device_path / "power_dpm_force_performance_level").read_text().strip() == "auto"
    assert (card.device_path / "pp_power_profile_mode").read_text().strip() == "4"


def test_apply_skips_power_cap_when_none(card: DetectedCard):
    hwmon_cap = card.device_path / "hwmon" / "hwmon0" / "power1_cap"
    original = hwmon_cap.read_text()
    drv = GpuDriver(card=card)
    drv.apply(Profile("idle", "auto", 5, None))
    assert hwmon_cap.read_text() == original


def test_apply_writes_power_cap_in_microwatts(card: DetectedCard):
    drv = GpuDriver(card=card)
    drv.apply(Profile("gaming", "auto", 1, 280))
    hwmon_cap = card.device_path / "hwmon" / "hwmon0" / "power1_cap"
    assert hwmon_cap.read_text().strip() == "280000000"


def test_apply_is_idempotent(card: DetectedCard):
    drv = GpuDriver(card=card)
    drv.apply(Profile("compute", "auto", 4, None))

    # Tamper externally — if we reapply the same profile, driver should skip (no write).
    (card.device_path / "pp_power_profile_mode").write_text("99\n")
    drv.apply(Profile("compute", "auto", 4, None))
    assert (card.device_path / "pp_power_profile_mode").read_text().strip() == "99"

    # But a different profile does write.
    drv.apply(Profile("gaming", "auto", 1, None))
    assert (card.device_path / "pp_power_profile_mode").read_text().strip() == "1"


def test_apply_survives_oserror_keeps_last_state(card: DetectedCard, caplog):
    drv = GpuDriver(card=card)
    drv.apply(Profile("compute", "auto", 4, None))

    # Make the file unwritable to trigger OSError on next apply.
    target = card.device_path / "pp_power_profile_mode"
    target.chmod(0o444)
    try:
        drv.apply(Profile("gaming", "auto", 1, None))
    finally:
        target.chmod(0o644)

    assert "sysfs write failed" in caplog.text.lower()
    # Last-known-good profile stays 'compute', so reapplying 'compute' still no-ops.
    (card.device_path / "pp_power_profile_mode").write_text("4\n")
    drv.apply(Profile("compute", "auto", 4, None))
    # No exception raised; cycle completed without tampering.


def test_reset_writes_auto_and_zero(card: DetectedCard):
    (card.device_path / "power_dpm_force_performance_level").write_text("high\n")
    (card.device_path / "pp_power_profile_mode").write_text("3\n")
    drv = GpuDriver(card=card)
    drv.reset_to_defaults()
    assert (card.device_path / "power_dpm_force_performance_level").read_text().strip() == "auto"
    assert (card.device_path / "pp_power_profile_mode").read_text().strip() == "0"
```

- [ ] **Step 2: Run tests, verify all fail**

Expected: `ModuleNotFoundError: No module named 'balu_power.gpu_driver'`.

- [ ] **Step 3: Implement `power/balu_power/gpu_driver.py`**

```python
"""Write Profile objects to /sys/class/drm/card*/… paths.

Idempotent: tracks the last successfully applied Profile and skips redundant
writes. Tolerates OSError by logging WARN; the last-known-good state stays
recorded so subsequent applies keep working.
"""
from __future__ import annotations

import logging
from pathlib import Path

from balu_power.hw_detect import DetectedCard
from balu_power.profiles import Profile

_log = logging.getLogger(__name__)


class GpuDriver:
    def __init__(self, card: DetectedCard) -> None:
        self._card = card
        self._last_applied: Profile | None = None

    @property
    def last_applied(self) -> Profile | None:
        return self._last_applied

    def apply(self, profile: Profile) -> None:
        if self._last_applied == profile:
            return
        prev = self._last_applied.name if self._last_applied else "(none)"
        try:
            self._write(
                self._card.device_path / "power_dpm_force_performance_level",
                profile.performance_level,
            )
            self._write(
                self._card.device_path / "pp_power_profile_mode",
                str(profile.power_profile_mode),
            )
            if profile.power_cap_w is not None:
                cap_file = self._find_hwmon_cap_file()
                if cap_file is not None:
                    self._write(cap_file, str(profile.power_cap_w * 1_000_000))
                else:
                    _log.warning("power1_cap file not found; skipping cap write")
            self._last_applied = profile
            _log.info("transition %s -> %s", prev, profile.name)
        except OSError as exc:
            _log.warning("sysfs write failed applying %s: %s", profile.name, exc)

    def reset_to_defaults(self) -> None:
        """Write kernel bootup defaults. Called from ExecStopPost."""
        try:
            self._write(
                self._card.device_path / "power_dpm_force_performance_level",
                "auto",
            )
            self._write(
                self._card.device_path / "pp_power_profile_mode",
                "0",
            )
            self._last_applied = None
        except OSError as exc:
            _log.warning("sysfs reset failed: %s", exc)

    def _write(self, path: Path, value: str) -> None:
        path.write_text(value + "\n")

    def _find_hwmon_cap_file(self) -> Path | None:
        hwmon_root = self._card.device_path / "hwmon"
        if not hwmon_root.exists():
            return None
        for child in sorted(hwmon_root.iterdir()):
            cap = child / "power1_cap"
            if cap.exists():
                return cap
        return None
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
.venv/bin/pytest power/tests/unit/test_gpu_driver.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add power/balu_power/gpu_driver.py power/tests/unit/test_gpu_driver.py
git commit -m "feat(power): add idempotent sysfs GPU driver with reset hook"
```

---

## Task 8: `daemon.py` — async socket loop (claim/release/status/reload)

Wires the pure pieces: accepts connections, parses requests, mutates the registry, asks the reconciler to drive the driver. No yet signal handling or ExecStopPost integration — those come in Task 9.

**Files:**
- Create: `power/balu_power/daemon.py`
- Create: `power/tests/integration/test_daemon_roundtrip.py`

- [ ] **Step 1: Write failing integration test** — `power/tests/integration/test_daemon_roundtrip.py`

```python
import asyncio
import json
from pathlib import Path

import pytest

from balu_power.daemon import Daemon
from balu_power.gpu_driver import GpuDriver
from balu_power.hw_detect import DetectedCard
from balu_power.profiles import DEFAULT_PRIORITY, DEFAULT_PROFILES, ProfileConfig


@pytest.fixture
def card(mock_sysfs: Path) -> DetectedCard:
    drm = mock_sysfs / "class" / "drm" / "card0"
    return DetectedCard(
        card="card0", drm_path=drm, device_path=drm / "device",
        vendor_id="0x1002", device_id="0x744c",
        is_amd=True, is_known_rdna3=True,
    )


@pytest.fixture
def config() -> ProfileConfig:
    return ProfileConfig(
        profiles=DEFAULT_PROFILES, priority=list(DEFAULT_PRIORITY), card="card0"
    )


async def _send(socket_path: Path, request: dict) -> dict:
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write((json.dumps(request) + "\n").encode())
    await writer.drain()
    response_line = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return json.loads(response_line)


@pytest.mark.asyncio
async def test_claim_then_status(tmp_path: Path, card: DetectedCard, config: ProfileConfig):
    sock = tmp_path / "balu-power.sock"
    driver = GpuDriver(card)
    daemon = Daemon(socket_path=sock, driver=driver, config=config)
    serve = asyncio.create_task(daemon.serve_forever())
    await daemon.ready.wait()
    try:
        ok = await _send(sock, {"v": 1, "op": "claim", "client_id": "x",
                                "state": "compute", "ttl_seconds": 15})
        assert ok == {"ok": True}

        status = await _send(sock, {"v": 1, "op": "status"})
        assert status["ok"] is True
        assert status["current_state"] == "compute"
        assert len(status["claims"]) == 1
    finally:
        await daemon.shutdown()
        await serve


@pytest.mark.asyncio
async def test_release_falls_back_to_idle(tmp_path: Path, card: DetectedCard, config: ProfileConfig):
    sock = tmp_path / "balu-power.sock"
    driver = GpuDriver(card)
    daemon = Daemon(socket_path=sock, driver=driver, config=config)
    serve = asyncio.create_task(daemon.serve_forever())
    await daemon.ready.wait()
    try:
        await _send(sock, {"v": 1, "op": "claim", "client_id": "x",
                           "state": "compute", "ttl_seconds": 15})
        await _send(sock, {"v": 1, "op": "release", "client_id": "x"})
        status = await _send(sock, {"v": 1, "op": "status"})
        assert status["current_state"] == "idle"
    finally:
        await daemon.shutdown()
        await serve


@pytest.mark.asyncio
async def test_compute_beats_display_off(tmp_path: Path, card: DetectedCard, config: ProfileConfig):
    sock = tmp_path / "balu-power.sock"
    driver = GpuDriver(card)
    daemon = Daemon(socket_path=sock, driver=driver, config=config)
    serve = asyncio.create_task(daemon.serve_forever())
    await daemon.ready.wait()
    try:
        await _send(sock, {"v": 1, "op": "claim", "client_id": "display",
                           "state": "display-off", "ttl_seconds": None})
        await _send(sock, {"v": 1, "op": "claim", "client_id": "ollama",
                           "state": "compute", "ttl_seconds": 30})
        status = await _send(sock, {"v": 1, "op": "status"})
        assert status["current_state"] == "compute"
    finally:
        await daemon.shutdown()
        await serve


@pytest.mark.asyncio
async def test_unknown_state_returns_error(tmp_path: Path, card: DetectedCard, config: ProfileConfig):
    sock = tmp_path / "balu-power.sock"
    driver = GpuDriver(card)
    daemon = Daemon(socket_path=sock, driver=driver, config=config)
    serve = asyncio.create_task(daemon.serve_forever())
    await daemon.ready.wait()
    try:
        resp = await _send(sock, {"v": 1, "op": "claim", "client_id": "x",
                                  "state": "turbo", "ttl_seconds": 5})
        assert resp == {"ok": False, "error": "unknown_state",
                        "message": "state 'turbo' not in profiles"}
    finally:
        await daemon.shutdown()
        await serve
```

- [ ] **Step 2: Run tests, verify all fail**

Expected: `ModuleNotFoundError: No module named 'balu_power.daemon'`.

- [ ] **Step 3: Implement `power/balu_power/daemon.py`**

```python
"""asyncio Unix-socket daemon.

Composition: owns the ClaimRegistry, calls GpuDriver.apply() on every
mutation. Time source is time.monotonic() by default; injectable for tests.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable

from balu_power.gpu_driver import GpuDriver
from balu_power.profiles import Profile, ProfileConfig, profile_by_name
from balu_power.protocol import (
    ClaimRequest,
    ReleaseRequest,
    ReloadRequest,
    Response,
    StatusRequest,
    parse_request,
    serialize_response,
)
from balu_power.registry import ClaimRegistry

_log = logging.getLogger(__name__)


class Daemon:
    def __init__(
        self,
        *,
        socket_path: Path,
        driver: GpuDriver,
        config: ProfileConfig,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._socket_path = socket_path
        self._driver = driver
        self._config = config
        self._clock = clock
        self._registry = ClaimRegistry(priority=config.priority)
        self._server: asyncio.base_events.Server | None = None
        self._shutdown = asyncio.Event()
        self.ready = asyncio.Event()

    async def serve_forever(self) -> None:
        if self._socket_path.exists():
            self._socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(self._socket_path)
        )
        self._socket_path.chmod(0o660)
        self._apply_current()     # write initial idle profile
        _log.info("balu-power listening on %s", self._socket_path)
        self.ready.set()
        async with self._server:
            try:
                await self._shutdown.wait()
            finally:
                self._server.close()
                await self._server.wait_closed()
                try:
                    self._socket_path.unlink()
                except FileNotFoundError:
                    pass

    async def shutdown(self) -> None:
        self._shutdown.set()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                response = self._process_line(line.rstrip(b"\n"))
                writer.write(serialize_response(response))
                await writer.drain()
        except Exception:
            _log.exception("client handler crashed")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _process_line(self, line: bytes) -> Response:
        try:
            req = parse_request(line)
        except ValueError as exc:
            code, _, message = str(exc).partition(":")
            return Response.failure(code.strip(), message.strip() or "invalid request")

        if isinstance(req, ClaimRequest):
            return self._handle_claim(req)
        if isinstance(req, ReleaseRequest):
            return self._handle_release(req)
        if isinstance(req, StatusRequest):
            return self._handle_status()
        if isinstance(req, ReloadRequest):
            return Response.failure("not_implemented", "reload not yet wired")
        return Response.failure("unknown_op", repr(req))

    def _handle_claim(self, req: ClaimRequest) -> Response:
        if not self._is_valid_state(req.state):
            return Response.failure(
                "unknown_state", f"state {req.state!r} not in profiles"
            )
        self._registry.claim(
            req.client_id, req.state, req.ttl_seconds, self._clock()
        )
        self._apply_current()
        return Response.success()

    def _handle_release(self, req: ReleaseRequest) -> Response:
        self._registry.release(req.client_id)
        self._apply_current()
        return Response.success()

    def _handle_status(self) -> Response:
        now = self._clock()
        self._registry.purge_expired(now)
        state = self._registry.resolve(now)
        claims = self._registry.snapshot(now)
        return Response.status(state, claims)

    def _apply_current(self) -> None:
        now = self._clock()
        self._registry.purge_expired(now)
        state = self._registry.resolve(now)
        profile = self._profile(state)
        self._driver.apply(profile)

    def _profile(self, name: str) -> Profile:
        return profile_by_name(self._config.profiles, name)

    def _is_valid_state(self, name: str) -> bool:
        return any(p.name == name for p in self._config.profiles)
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
.venv/bin/pytest power/tests/integration/test_daemon_roundtrip.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add power/balu_power/daemon.py power/tests/integration/test_daemon_roundtrip.py
git commit -m "feat(power): add asyncio Unix-socket daemon with claim/release/status"
```

---

## Task 9: `daemon.py` — reload, reconciler tick, signals, `__main__`

Add the remaining pieces: periodic reconcile for TTL-expiry, `reload` op wired to `load_profiles()`, SIGTERM/SIGINT clean shutdown with `reset_to_defaults()`, and a `main()` entry point. Also add a tick-driven expiry integration test.

**Files:**
- Modify: `power/balu_power/daemon.py`
- Create: `power/balu_power/__main__.py`
- Modify: `power/tests/integration/test_daemon_roundtrip.py`

- [ ] **Step 1: Add failing tests** — append to `test_daemon_roundtrip.py`

```python
@pytest.mark.asyncio
async def test_ttl_expiry_via_reconcile_tick(
    tmp_path: Path, card: DetectedCard, config: ProfileConfig
):
    sock = tmp_path / "balu-power.sock"
    driver = GpuDriver(card)
    # Injected clock so we control expiry without sleeping.
    now = [100.0]
    daemon = Daemon(
        socket_path=sock, driver=driver, config=config,
        clock=lambda: now[0], reconcile_interval_s=0.05,
    )
    serve = asyncio.create_task(daemon.serve_forever())
    await daemon.ready.wait()
    try:
        await _send(sock, {"v": 1, "op": "claim", "client_id": "x",
                           "state": "compute", "ttl_seconds": 10})
        status = await _send(sock, {"v": 1, "op": "status"})
        assert status["current_state"] == "compute"

        # Jump the clock past TTL; reconcile tick should notice within its interval.
        now[0] = 200.0
        await asyncio.sleep(0.2)       # give the tick two cycles

        status = await _send(sock, {"v": 1, "op": "status"})
        assert status["current_state"] == "idle"
    finally:
        await daemon.shutdown()
        await serve


@pytest.mark.asyncio
async def test_reload_reapplies_current_state(
    tmp_path: Path, card: DetectedCard, config: ProfileConfig
):
    sock = tmp_path / "balu-power.sock"
    driver = GpuDriver(card)
    cfg_path = tmp_path / "profiles.yaml"
    daemon = Daemon(
        socket_path=sock, driver=driver, config=config, config_path=cfg_path
    )
    serve = asyncio.create_task(daemon.serve_forever())
    await daemon.ready.wait()
    try:
        cfg_path.write_text(
            "profiles:\n  gaming:\n    performance_level: high\n"
            "    power_profile_mode: 1\n"
        )
        resp = await _send(sock, {"v": 1, "op": "reload"})
        assert resp == {"ok": True}
        await _send(sock, {"v": 1, "op": "claim", "client_id": "x",
                           "state": "gaming", "ttl_seconds": None})
        level = (card.device_path / "power_dpm_force_performance_level").read_text().strip()
        assert level == "high"
    finally:
        await daemon.shutdown()
        await serve


@pytest.mark.asyncio
async def test_shutdown_resets_sysfs(
    tmp_path: Path, card: DetectedCard, config: ProfileConfig
):
    sock = tmp_path / "balu-power.sock"
    (card.device_path / "power_dpm_force_performance_level").write_text("high\n")
    driver = GpuDriver(card)
    daemon = Daemon(socket_path=sock, driver=driver, config=config)
    serve = asyncio.create_task(daemon.serve_forever())
    await daemon.ready.wait()
    await _send(sock, {"v": 1, "op": "claim", "client_id": "x",
                       "state": "gaming", "ttl_seconds": None})
    # Sanity: gaming applied → level="auto" (spec default).
    assert (card.device_path / "power_dpm_force_performance_level").read_text().strip() == "auto"

    await daemon.shutdown()
    await serve

    # After shutdown, reset_to_defaults should have written auto + 0.
    assert (card.device_path / "pp_power_profile_mode").read_text().strip() == "0"
```

- [ ] **Step 2: Run tests, verify they fail**

Expected: missing kwargs `reconcile_interval_s`, `config_path`; missing `reload` behavior.

- [ ] **Step 3: Extend `power/balu_power/daemon.py`**

Change the `__init__` signature and add the reconciler/reload/reset plumbing:

```python
# Replace the __init__ signature:
    def __init__(
        self,
        *,
        socket_path: Path,
        driver: GpuDriver,
        config: ProfileConfig,
        clock: Callable[[], float] = time.monotonic,
        reconcile_interval_s: float = 1.0,
        config_path: Path | None = None,
    ) -> None:
        self._socket_path = socket_path
        self._driver = driver
        self._config = config
        self._clock = clock
        self._reconcile_interval_s = reconcile_interval_s
        self._config_path = config_path
        self._registry = ClaimRegistry(priority=config.priority)
        self._server: asyncio.base_events.Server | None = None
        self._shutdown = asyncio.Event()
        self._reconcile_task: asyncio.Task | None = None
        self.ready = asyncio.Event()
```

Replace `serve_forever`:

```python
    async def serve_forever(self) -> None:
        if self._socket_path.exists():
            self._socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(self._socket_path)
        )
        self._socket_path.chmod(0o660)
        self._apply_current()
        self._reconcile_task = asyncio.create_task(self._reconcile_loop())
        _log.info("balu-power listening on %s", self._socket_path)
        self.ready.set()
        try:
            await self._shutdown.wait()
        finally:
            if self._reconcile_task:
                self._reconcile_task.cancel()
                try:
                    await self._reconcile_task
                except asyncio.CancelledError:
                    pass
            self._server.close()
            await self._server.wait_closed()
            try:
                self._socket_path.unlink()
            except FileNotFoundError:
                pass
            self._driver.reset_to_defaults()

    async def _reconcile_loop(self) -> None:
        while not self._shutdown.is_set():
            self._apply_current()
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(), timeout=self._reconcile_interval_s
                )
            except TimeoutError:
                continue
```

Replace the `reload` branch in `_process_line`:

```python
        if isinstance(req, ReloadRequest):
            return self._handle_reload()
```

Add `_handle_reload`:

```python
    def _handle_reload(self) -> Response:
        if self._config_path is None:
            return Response.failure("reload_unavailable", "no config path configured")
        try:
            from balu_power.profiles import load_profiles  # local import to avoid cycle
            new_config = load_profiles(self._config_path)
        except Exception as exc:
            return Response.failure("reload_failed", str(exc))
        # Priority changes mean the registry must be rebuilt with new ordering.
        self._config = new_config
        old_claims = self._registry.snapshot(self._clock())
        self._registry = ClaimRegistry(priority=new_config.priority)
        for c in old_claims:
            ttl = c["expires_in_s"]
            self._registry.claim(c["client_id"], c["state"], ttl, self._clock())
        self._apply_current()
        return Response.success()
```

- [ ] **Step 4: Create `power/balu_power/__main__.py`**

```python
"""CLI entry: `balu-power`. Wires config loading, hw detection, signal handlers."""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from balu_power.daemon import Daemon
from balu_power.gpu_driver import GpuDriver
from balu_power.hw_detect import HardwareError, detect_card
from balu_power.profiles import ProfileConfigError, load_profiles


def main() -> int:
    parser = argparse.ArgumentParser(prog="balu-power")
    parser.add_argument("--socket", default="/run/balu-power.sock", type=Path)
    parser.add_argument("--config", default="/etc/balu-power/profiles.yaml", type=Path)
    parser.add_argument("--sys-root", default="/sys", type=Path,
                        help="override for tests")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s balu-power: %(message)s",
    )

    try:
        config = load_profiles(args.config)
    except ProfileConfigError as exc:
        logging.error("config error: %s", exc)
        return 2

    try:
        card = detect_card(sys_root=args.sys_root, preferred_card=config.card)
    except HardwareError as exc:
        logging.error("hardware detection failed: %s", exc)
        return 3

    driver = GpuDriver(card=card)
    daemon = Daemon(
        socket_path=args.socket, driver=driver, config=config,
        config_path=args.config,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _on_signal() -> None:
        logging.info("shutdown signal received")
        asyncio.run_coroutine_threadsafe(daemon.shutdown(), loop)

    loop.add_signal_handler(signal.SIGTERM, _on_signal)
    loop.add_signal_handler(signal.SIGINT, _on_signal)

    try:
        loop.run_until_complete(daemon.serve_forever())
    finally:
        loop.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests, verify they pass**

```bash
.venv/bin/pytest power/tests/integration/test_daemon_roundtrip.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add power/balu_power/daemon.py power/balu_power/__main__.py \
        power/tests/integration/test_daemon_roundtrip.py
git commit -m "feat(power): add reconcile tick, reload op, signal-driven shutdown"
```

---

## Task 10: `balu_powerctl` — CLI client

Thin wrapper around the socket. Hardcodes `client_id="manual"`. Sub-commands: `claim`, `release`, `status`.

**Files:**
- Create: `power/balu_powerctl/__init__.py`
- Create: `power/balu_powerctl/__main__.py`

- [ ] **Step 1: Create `power/balu_powerctl/__init__.py`** (empty)

- [ ] **Step 2: Write `power/balu_powerctl/__main__.py`**

```python
"""balu-powerctl — user CLI for the balu-power daemon.

All claims use client_id="manual". No privilege required beyond
group membership allowing socket access.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

DEFAULT_SOCKET = Path("/run/balu-power.sock")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="balu-powerctl")
    parser.add_argument("--socket", default=DEFAULT_SOCKET, type=Path)
    sub = parser.add_subparsers(dest="cmd", required=True)

    claim = sub.add_parser("claim", help="Claim a state under client_id='manual'")
    claim.add_argument("state")
    claim.add_argument("--ttl", type=int, default=None,
                       help="seconds until the claim expires; default infinite")

    sub.add_parser("release", help="Release the manual claim")
    sub.add_parser("status", help="Show daemon state + claims")

    args = parser.parse_args(argv)

    if args.cmd == "claim":
        body = {"v": 1, "op": "claim", "client_id": "manual",
                "state": args.state, "ttl_seconds": args.ttl}
    elif args.cmd == "release":
        body = {"v": 1, "op": "release", "client_id": "manual"}
    elif args.cmd == "status":
        body = {"v": 1, "op": "status"}
    else:                                       # unreachable (required=True)
        raise SystemExit(2)

    response = _send(args.socket, body)
    print(json.dumps(response, indent=2))
    return 0 if response.get("ok") else 1


def _send(socket_path: Path, request: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(socket_path))
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    line, _, _ = buf.partition(b"\n")
    return json.loads(line or b"{}")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify manually against a running daemon in /tmp**

(This is exercised by integration tests in later tasks; no unit test needed for the CLI — every behavior is shared with the protocol parser tested in Task 4.)

```bash
# Smoke check that imports work and --help prints.
.venv/bin/python -m balu_powerctl --help
```

Expected: usage output listing `claim`, `release`, `status`.

- [ ] **Step 4: Commit**

```bash
git add power/balu_powerctl/
git commit -m "feat(power): add balu-powerctl CLI client"
```

---

## Task 11: `ollama_watcher.py` — Ollama-state poller

Polls `http://localhost:11434/api/ps`. Pushes `compute` while a model is active (non-empty `size_vram` and a recent `expires_at`), `llm-idle` while loaded-but-idle, releases when no models are loaded. Refresh every 10 s with `ttl=15 s`.

**Files:**
- Create: `power/watchers/__init__.py`
- Create: `power/watchers/ollama_watcher.py`
- Create: `power/tests/integration/test_ollama_watcher.py`

- [ ] **Step 1: Create `power/watchers/__init__.py`** (empty)

- [ ] **Step 2: Write failing integration test** — `power/tests/integration/test_ollama_watcher.py`

```python
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from balu_power.daemon import Daemon
from balu_power.gpu_driver import GpuDriver
from balu_power.hw_detect import DetectedCard
from balu_power.profiles import DEFAULT_PRIORITY, DEFAULT_PROFILES, ProfileConfig
from watchers.ollama_watcher import OllamaWatcher


class _Handler(BaseHTTPRequestHandler):
    payload: dict = {"models": []}       # set by test
    generate_calls: list[dict] = []      # POST /api/generate bodies captured

    def do_GET(self):  # noqa: N802
        if self.path == "/api/ps":
            body = json.dumps(_Handler.payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):  # noqa: N802
        if self.path == "/api/generate":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            try:
                _Handler.generate_calls.append(json.loads(raw.decode("utf-8")))
            except Exception:
                _Handler.generate_calls.append({})
            body = b'{}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *_args):    # silence
        pass


@pytest.fixture
def ollama_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def card(mock_sysfs: Path) -> DetectedCard:
    drm = mock_sysfs / "class" / "drm" / "card0"
    return DetectedCard(
        card="card0", drm_path=drm, device_path=drm / "device",
        vendor_id="0x1002", device_id="0x744c",
        is_amd=True, is_known_rdna3=True,
    )


@pytest.fixture
def config() -> ProfileConfig:
    return ProfileConfig(
        profiles=DEFAULT_PROFILES, priority=list(DEFAULT_PRIORITY), card="card0"
    )


async def _read_status(sock: Path) -> dict:
    reader, writer = await asyncio.open_unix_connection(str(sock))
    writer.write(b'{"v":1,"op":"status"}\n')
    await writer.drain()
    line = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return json.loads(line)


@pytest.mark.asyncio
async def test_watcher_pushes_compute_when_model_active(
    tmp_path: Path, card: DetectedCard, config: ProfileConfig, ollama_server: str
):
    _Handler.payload = {"models": [{"name": "qwen", "size_vram": 10_000_000_000,
                                    "expires_at": "2099-01-01T00:00:00Z"}]}
    sock = tmp_path / "balu-power.sock"
    driver = GpuDriver(card)
    daemon = Daemon(socket_path=sock, driver=driver, config=config)
    serve = asyncio.create_task(daemon.serve_forever())
    await daemon.ready.wait()

    watcher = OllamaWatcher(ollama_url=ollama_server, socket_path=sock,
                            poll_interval_s=0.1, ttl_seconds=5)
    watch_task = asyncio.create_task(watcher.run())
    try:
        await asyncio.sleep(0.3)     # allow at least one poll+push
        status = await _read_status(sock)
        assert status["current_state"] == "compute"
    finally:
        watcher.stop()
        await watch_task
        await daemon.shutdown()
        await serve


@pytest.mark.asyncio
async def test_watcher_pushes_llm_idle_when_model_loaded_but_quiet(
    tmp_path: Path, card: DetectedCard, config: ProfileConfig, ollama_server: str
):
    # Loaded but no expires_at → our heuristic treats as llm-idle.
    _Handler.payload = {"models": [{"name": "qwen", "size_vram": 10_000_000_000}]}
    sock = tmp_path / "balu-power.sock"
    driver = GpuDriver(card)
    daemon = Daemon(socket_path=sock, driver=driver, config=config)
    serve = asyncio.create_task(daemon.serve_forever())
    await daemon.ready.wait()

    watcher = OllamaWatcher(ollama_url=ollama_server, socket_path=sock,
                            poll_interval_s=0.1, ttl_seconds=5)
    watch_task = asyncio.create_task(watcher.run())
    try:
        await asyncio.sleep(0.3)
        status = await _read_status(sock)
        assert status["current_state"] == "llm-idle"
    finally:
        watcher.stop()
        await watch_task
        await daemon.shutdown()
        await serve


@pytest.mark.asyncio
async def test_watcher_releases_when_no_models(
    tmp_path: Path, card: DetectedCard, config: ProfileConfig, ollama_server: str
):
    _Handler.payload = {"models": []}
    sock = tmp_path / "balu-power.sock"
    driver = GpuDriver(card)
    daemon = Daemon(socket_path=sock, driver=driver, config=config)
    serve = asyncio.create_task(daemon.serve_forever())
    await daemon.ready.wait()

    watcher = OllamaWatcher(ollama_url=ollama_server, socket_path=sock,
                            poll_interval_s=0.1, ttl_seconds=5)
    watch_task = asyncio.create_task(watcher.run())
    try:
        await asyncio.sleep(0.3)
        status = await _read_status(sock)
        assert status["current_state"] == "idle"
    finally:
        watcher.stop()
        await watch_task
        await daemon.shutdown()
        await serve


@pytest.mark.asyncio
async def test_watcher_unloads_model_on_idle_when_flag_set(
    tmp_path: Path, card: DetectedCard, config: ProfileConfig, ollama_server: str
):
    _Handler.payload = {"models": [{"name": "qwen", "size_vram": 10_000_000_000}]}
    _Handler.generate_calls.clear()
    sock = tmp_path / "balu-power.sock"
    driver = GpuDriver(card)
    daemon = Daemon(socket_path=sock, driver=driver, config=config)
    serve = asyncio.create_task(daemon.serve_forever())
    await daemon.ready.wait()

    watcher = OllamaWatcher(
        ollama_url=ollama_server, socket_path=sock,
        poll_interval_s=0.1, ttl_seconds=5, unload_on_idle=True,
    )
    watch_task = asyncio.create_task(watcher.run())
    try:
        await asyncio.sleep(0.3)   # first poll → transition to llm-idle → unload
        assert any(
            call.get("model") == "qwen" and call.get("keep_alive") == 0
            for call in _Handler.generate_calls
        ), f"expected keep_alive=0 post; got {_Handler.generate_calls}"
    finally:
        watcher.stop()
        await watch_task
        await daemon.shutdown()
        await serve
```

- [ ] **Step 3: Write `power/watchers/ollama_watcher.py`**

```python
"""Polls Ollama `/api/ps` and pushes claims to the balu-power daemon.

State mapping:
  - any model with a future `expires_at`                      → compute
  - any model without `expires_at` (loaded, idle)             → llm-idle
  - no models                                                 → release (no claim)

Client id: "ollama-watcher". Fixed TTL of 15 s; poll interval 10 s; so a
missed push simply drops us to idle after 15 s, no zombie state.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

CLIENT_ID = "ollama-watcher"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_SOCKET = Path("/run/balu-power.sock")

_log = logging.getLogger(__name__)


class OllamaWatcher:
    def __init__(
        self,
        *,
        ollama_url: str,
        socket_path: Path,
        poll_interval_s: float = 10.0,
        ttl_seconds: int = 15,
        unload_on_idle: bool = False,
    ) -> None:
        self._ollama_url = ollama_url.rstrip("/")
        self._socket_path = socket_path
        self._poll_interval_s = poll_interval_s
        self._ttl_seconds = ttl_seconds
        self._unload_on_idle = unload_on_idle
        self._stop = asyncio.Event()
        self._last_sent: str | None = None

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        async with httpx.AsyncClient(timeout=2.0) as client:
            while not self._stop.is_set():
                try:
                    state, loaded_models = await self._poll(client)
                    await self._dispatch(client, state, loaded_models)
                except Exception:
                    _log.exception("ollama-watcher poll failed")
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self._poll_interval_s
                    )
                except TimeoutError:
                    pass

    async def _poll(
        self, client: httpx.AsyncClient
    ) -> tuple[str | None, list[str]]:
        resp = await client.get(f"{self._ollama_url}/api/ps")
        resp.raise_for_status()
        models = resp.json().get("models", [])
        names = [m.get("name", "") for m in models if m.get("name")]
        if not models:
            return None, names
        now = datetime.now(timezone.utc)
        for m in models:
            expires = m.get("expires_at")
            if expires and _parse_iso(expires) > now:
                return "compute", names
        return "llm-idle", names

    async def _dispatch(
        self, client: httpx.AsyncClient, state: str | None, models: list[str]
    ) -> None:
        if state is None:
            if self._last_sent is not None:
                _send(self._socket_path, {"v": 1, "op": "release", "client_id": CLIENT_ID})
                self._last_sent = None
            return

        if state == "llm-idle" and self._unload_on_idle and self._last_sent != "llm-idle":
            for name in models:
                await self._evict(client, name)

        _send(self._socket_path, {
            "v": 1, "op": "claim", "client_id": CLIENT_ID,
            "state": state, "ttl_seconds": self._ttl_seconds,
        })
        self._last_sent = state

    async def _evict(self, client: httpx.AsyncClient, model: str) -> None:
        try:
            await client.post(
                f"{self._ollama_url}/api/generate",
                json={"model": model, "keep_alive": 0},
            )
        except Exception as exc:
            _log.warning("ollama unload failed for %s: %s", model, exc)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _send(socket_path: Path, body: dict) -> None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(str(socket_path))
            s.sendall((json.dumps(body) + "\n").encode("utf-8"))
            s.recv(4096)      # drain response
    except OSError as exc:
        _log.warning("socket push failed: %s", exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="balu-power-ollama-watcher")
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--socket", default=DEFAULT_SOCKET, type=Path)
    parser.add_argument("--poll-interval", type=float, default=10.0)
    parser.add_argument("--ttl", type=int, default=15)
    parser.add_argument("--config", default=Path("/etc/balu-power/profiles.yaml"),
                        type=Path,
                        help="Read llm-idle.ollama_unload from this yaml")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level,
                        format="%(asctime)s ollama-watcher: %(message)s")

    from balu_power.profiles import load_profiles, profile_by_name
    unload = False
    try:
        cfg = load_profiles(args.config)
        unload = profile_by_name(cfg.profiles, "llm-idle").ollama_unload
    except Exception as exc:
        _log.warning("could not read profiles config %s: %s", args.config, exc)

    watcher = OllamaWatcher(
        ollama_url=args.ollama_url, socket_path=args.socket,
        poll_interval_s=args.poll_interval, ttl_seconds=args.ttl,
        unload_on_idle=unload,
    )
    asyncio.run(watcher.run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
.venv/bin/pytest power/tests/integration/test_ollama_watcher.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add power/watchers/ power/tests/integration/test_ollama_watcher.py
git commit -m "feat(power): add ollama-watcher (compute/llm-idle polling)"
```

---

## Task 12: `display_watcher.py` — logind IdleHint subscriber

Subscribes to `PropertiesChanged` on `/org/freedesktop/login1/session/self`. Pushes `display-off` when `IdleHint` flips to `true`, releases when `false`. Pure DBus — no polling.

**Files:**
- Create: `power/watchers/display_watcher.py`
- Create: `power/tests/integration/test_display_watcher.py`

- [ ] **Step 1: Write failing integration test** — `power/tests/integration/test_display_watcher.py`

```python
"""DBus test uses python-dbusmock to simulate logind."""
import asyncio
import json
import subprocess
import time
from pathlib import Path

import pytest

from balu_power.daemon import Daemon
from balu_power.gpu_driver import GpuDriver
from balu_power.hw_detect import DetectedCard
from balu_power.profiles import DEFAULT_PRIORITY, DEFAULT_PROFILES, ProfileConfig

dbusmock = pytest.importorskip("dbusmock")


@pytest.fixture
def card(mock_sysfs: Path) -> DetectedCard:
    drm = mock_sysfs / "class" / "drm" / "card0"
    return DetectedCard(
        card="card0", drm_path=drm, device_path=drm / "device",
        vendor_id="0x1002", device_id="0x744c",
        is_amd=True, is_known_rdna3=True,
    )


@pytest.fixture
def config() -> ProfileConfig:
    return ProfileConfig(
        profiles=DEFAULT_PROFILES, priority=list(DEFAULT_PRIORITY), card="card0"
    )


@pytest.fixture
def logind_mock(monkeypatch):
    """Start a dbusmock logind on a private session bus."""
    bus = dbusmock.DBusTestCase()
    bus.setUp()
    bus.start_session_bus()
    p_mock, obj = bus.spawn_server_template(
        "logind", {}, stdout=subprocess.DEVNULL
    )
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", bus.get_dbus_address("session"))
    try:
        yield obj
    finally:
        p_mock.terminate()
        p_mock.wait()
        bus.tearDown()


async def _read_status(sock: Path) -> dict:
    reader, writer = await asyncio.open_unix_connection(str(sock))
    writer.write(b'{"v":1,"op":"status"}\n')
    await writer.drain()
    line = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return json.loads(line)


@pytest.mark.asyncio
async def test_watcher_pushes_display_off_when_idle_hint_true(
    tmp_path, card, config, logind_mock
):
    from watchers.display_watcher import DisplayWatcher
    sock = tmp_path / "balu-power.sock"
    driver = GpuDriver(card)
    daemon = Daemon(socket_path=sock, driver=driver, config=config)
    serve = asyncio.create_task(daemon.serve_forever())
    await daemon.ready.wait()

    watcher = DisplayWatcher(socket_path=sock, use_system_bus=False)
    watch_task = asyncio.create_task(watcher.run())
    try:
        await asyncio.sleep(0.3)
        logind_mock.SetProperty(
            "org.freedesktop.login1.Session", "IdleHint", True
        )
        await asyncio.sleep(0.3)
        status = await _read_status(sock)
        assert status["current_state"] == "display-off"

        logind_mock.SetProperty(
            "org.freedesktop.login1.Session", "IdleHint", False
        )
        await asyncio.sleep(0.3)
        status = await _read_status(sock)
        assert status["current_state"] == "idle"
    finally:
        watcher.stop()
        await watch_task
        await daemon.shutdown()
        await serve
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
.venv/bin/pytest power/tests/integration/test_display_watcher.py -v
```

Expected: `ModuleNotFoundError: No module named 'watchers.display_watcher'`.

- [ ] **Step 3: Implement `power/watchers/display_watcher.py`**

```python
"""Subscribes to logind session IdleHint; pushes display-off claim."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import socket
import sys
from pathlib import Path

from dbus_next import BusType, Message, MessageType
from dbus_next.aio import MessageBus

CLIENT_ID = "display-watcher"
DEFAULT_SOCKET = Path("/run/balu-power.sock")

_log = logging.getLogger(__name__)


class DisplayWatcher:
    def __init__(
        self,
        *,
        socket_path: Path,
        use_system_bus: bool = True,
    ) -> None:
        self._socket_path = socket_path
        self._bus_type = BusType.SYSTEM if use_system_bus else BusType.SESSION
        self._stop = asyncio.Event()
        self._last_sent: str | None = None
        self._bus: MessageBus | None = None

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        self._bus = await MessageBus(bus_type=self._bus_type).connect()
        # Introspect to get the Session interface + initial IdleHint.
        introspect = await self._bus.introspect(
            "org.freedesktop.login1", "/org/freedesktop/login1/session/self"
        )
        proxy = self._bus.get_proxy_object(
            "org.freedesktop.login1",
            "/org/freedesktop/login1/session/self",
            introspect,
        )
        props = proxy.get_interface("org.freedesktop.DBus.Properties")
        initial = await props.call_get("org.freedesktop.login1.Session", "IdleHint")
        self._apply(bool(initial.value))

        def on_properties_changed(iface: str, changed: dict, _invalidated: list):
            if iface != "org.freedesktop.login1.Session":
                return
            if "IdleHint" in changed:
                self._apply(bool(changed["IdleHint"].value))

        props.on_properties_changed(on_properties_changed)
        await self._stop.wait()
        self._bus.disconnect()

    def _apply(self, idle: bool) -> None:
        if idle:
            _send(self._socket_path, {
                "v": 1, "op": "claim", "client_id": CLIENT_ID,
                "state": "display-off", "ttl_seconds": None,
            })
            self._last_sent = "display-off"
        else:
            if self._last_sent is not None:
                _send(self._socket_path, {
                    "v": 1, "op": "release", "client_id": CLIENT_ID,
                })
                self._last_sent = None


def _send(socket_path: Path, body: dict) -> None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(str(socket_path))
            s.sendall((json.dumps(body) + "\n").encode("utf-8"))
            s.recv(4096)
    except OSError as exc:
        _log.warning("socket push failed: %s", exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="balu-power-display-watcher")
    parser.add_argument("--socket", default=DEFAULT_SOCKET, type=Path)
    parser.add_argument("--session-bus", action="store_true",
                        help="Use session bus (tests). Default: system bus.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level,
                        format="%(asctime)s display-watcher: %(message)s")
    watcher = DisplayWatcher(
        socket_path=args.socket, use_system_bus=not args.session_bus,
    )
    asyncio.run(watcher.run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
.venv/bin/pytest power/tests/integration/test_display_watcher.py -v
```

Expected: 1 passed. If `python-dbusmock`/logind template is missing on CI, test is skipped (`importorskip`).

- [ ] **Step 5: Commit**

```bash
git add power/watchers/display_watcher.py power/tests/integration/test_display_watcher.py
git commit -m "feat(power): add display-watcher (logind IdleHint subscriber)"
```

---

## Task 13: Systemd units + contrib scripts

Ship the user-facing runtime artifacts. No tests — these are reviewed visually, installed manually, verified in Task 16.

**Files:**
- Create: `power/contrib/systemd/balu-power.service`
- Create: `power/contrib/systemd/balu-power-ollama-watcher.service`
- Create: `power/contrib/systemd/balu-power-display-watcher.service`
- Create: `power/contrib/balu-power-reset`
- Create: `power/contrib/gamemode-hook.ini`
- Create: `power/contrib/safe-defaults.conf`

- [ ] **Step 1: `power/contrib/systemd/balu-power.service`** (system unit)

```ini
[Unit]
Description=BaluPower — intelligent GPU power management daemon
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/bin/balu-power
ExecStopPost=/usr/libexec/balu-power-reset
Restart=on-failure
RestartSec=2
StartLimitBurst=3
StartLimitIntervalSec=60

ProtectSystem=strict
ReadWritePaths=/sys/class/drm /sys/class/hwmon /run
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
CapabilityBoundingSet=CAP_SYS_ADMIN CAP_DAC_OVERRIDE
RestrictAddressFamilies=AF_UNIX
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: `power/contrib/systemd/balu-power-ollama-watcher.service`** (user unit)

```ini
[Unit]
Description=BaluPower — Ollama state watcher
After=default.target
Requires=default.target

[Service]
Type=simple
ExecStart=/usr/bin/balu-power-ollama-watcher
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

- [ ] **Step 3: `power/contrib/systemd/balu-power-display-watcher.service`** (user unit)

```ini
[Unit]
Description=BaluPower — logind IdleHint watcher
After=default.target
Requires=default.target

[Service]
Type=simple
ExecStart=/usr/bin/balu-power-display-watcher
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

- [ ] **Step 4: `power/contrib/balu-power-reset`** (installed to `/usr/libexec/`)

```bash
#!/bin/sh
# Unconditionally restore kernel defaults on daemon stop/crash.
# Must be runnable without Python; hard-coded paths only.
set -e

CARD="${1:-card0}"
DEV="/sys/class/drm/${CARD}/device"

if [ -w "${DEV}/power_dpm_force_performance_level" ]; then
    echo auto > "${DEV}/power_dpm_force_performance_level" || true
fi
if [ -w "${DEV}/pp_power_profile_mode" ]; then
    echo 0 > "${DEV}/pp_power_profile_mode" || true
fi
```

Make it executable:

```bash
chmod +x power/contrib/balu-power-reset
```

- [ ] **Step 5: `power/contrib/gamemode-hook.ini`**

```ini
# Drop into ~/.config/gamemode.ini (merge with existing sections).
[custom]
start=/usr/bin/balu-powerctl claim gaming
end=/usr/bin/balu-powerctl release
```

- [ ] **Step 6: `power/contrib/safe-defaults.conf`**

```ini
# Non-overridable upper bounds for balu-power. Daemon rejects
# /etc/balu-power/profiles.yaml that exceeds these.
# Mirror values of balu_power/profiles.py constants.
[limits]
max_power_cap_w = 400
```

- [ ] **Step 7: Commit**

```bash
git add power/contrib/
git commit -m "feat(power): add systemd units, reset hook, gamemode snippet"
```

---

## Task 14: Installer + docs

Make the install story explicit. The install script is minimal — it exists only so the setup doc can say "run this."

**Files:**
- Create: `power/contrib/install.sh`
- Create: `docs/power/setup.md`
- Create: `docs/power/configuration.md`
- Create: `docs/power/clients.md`

- [ ] **Step 1: `power/contrib/install.sh`**

```bash
#!/bin/bash
# Install BaluPower daemon + user-session watchers.
# Run as a regular user with sudo available. Idempotent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
POWER_DIR="${REPO_ROOT}/power"

echo "== balu-power install =="

# 1. Create group + add current user
if ! getent group balu-power >/dev/null; then
    sudo groupadd --system balu-power
fi
sudo gpasswd -a "$USER" balu-power

# 2. Python install (editable for now; switch to PEP 668 wheel in Phase 2)
sudo -H "${REPO_ROOT}/.venv/bin/pip" install -e "${POWER_DIR}"

# 3. System unit + reset hook
sudo install -m 0755 "${POWER_DIR}/contrib/balu-power-reset" /usr/libexec/balu-power-reset
sudo install -m 0644 "${POWER_DIR}/contrib/systemd/balu-power.service" /etc/systemd/system/
sudo install -m 0644 "${POWER_DIR}/contrib/safe-defaults.conf" /etc/balu-power/safe-defaults.conf

# 4. User units
mkdir -p "$HOME/.config/systemd/user"
install -m 0644 \
    "${POWER_DIR}/contrib/systemd/balu-power-ollama-watcher.service" \
    "${POWER_DIR}/contrib/systemd/balu-power-display-watcher.service" \
    "$HOME/.config/systemd/user/"

# 5. Enable + start
sudo systemctl daemon-reload
sudo systemctl enable --now balu-power.service
systemctl --user daemon-reload
systemctl --user enable --now balu-power-ollama-watcher.service
systemctl --user enable --now balu-power-display-watcher.service

echo
echo "Install complete. Log out and back in for the balu-power group to apply."
echo "Verify with: balu-powerctl status"
```

Make executable:

```bash
chmod +x power/contrib/install.sh
```

- [ ] **Step 2: `docs/power/setup.md`**

```markdown
# BaluPower — Setup

BaluPower is v1-scoped to **AMD RDNA3 on Linux** (RX 7900 XT/XTX, 7800 XT, 7700 XT, 7600). NVIDIA and Intel are out of scope.

## Prerequisites

- systemd-based distro (Debian 12+, Ubuntu 24.04+, Fedora 40+, Arch).
- Kernel 6.6+ (earlier kernels have the high-MCLK idle bug; upgrade first).
- Python 3.12+.
- GameMode installed and runnable (`gamemoderun --help`).
- Ollama running on `localhost:11434` (optional; watcher still starts, just idle).

## Install

```bash
git clone https://github.com/your-org/Balu_Code.git
cd Balu_Code
uv venv
uv pip install -e .
./power/contrib/install.sh
```

The script:

1. Creates the `balu-power` system group and adds your user to it.
2. Installs the daemon (editable) into the repo's venv.
3. Drops the system unit, reset hook, and safe-defaults config.
4. Installs user units for ollama-watcher and display-watcher.
5. Enables and starts all three services.

**Important**: log out and back in after install for the group membership to take effect.

## GameMode hook

Add the snippet from `power/contrib/gamemode-hook.ini` to your `~/.config/gamemode.ini`. Example (merge with existing sections):

```ini
[custom]
start=/usr/bin/balu-powerctl claim gaming
end=/usr/bin/balu-powerctl release
```

Then in Steam, add `gamemoderun %command%` to the launch options of each game.

## Uninstall

```bash
sudo systemctl disable --now balu-power.service
systemctl --user disable --now balu-power-ollama-watcher.service balu-power-display-watcher.service
sudo rm /etc/systemd/system/balu-power.service /usr/libexec/balu-power-reset
rm ~/.config/systemd/user/balu-power-*.service
sudo groupdel balu-power
```

## Verify

```bash
balu-powerctl status
journalctl -u balu-power -f
systemctl --user status balu-power-ollama-watcher balu-power-display-watcher
```
```

- [ ] **Step 3: `docs/power/configuration.md`**

```markdown
# BaluPower — Configuration

## Defaults

Out of the box, BaluPower uses the hardcoded profile catalog in `power/balu_power/profiles.py`. No config file is required. Defaults:

| Profile | Priority | `power_dpm_force_performance_level` | `pp_power_profile_mode` | `power1_cap` |
|---|---|---|---|---|
| `gaming` | 4 | auto | 1 (3D_FULL_SCREEN) | not touched |
| `compute` | 3 | auto | 4 (COMPUTE) | not touched |
| `display-off` | 2 | low | 5 (POWER_SAVING) | not touched |
| `llm-idle` | 1 | auto | 5 (POWER_SAVING) | not touched |
| `idle` | 0 (fallback) | auto | 5 (POWER_SAVING) | not touched |

## Overriding via `/etc/balu-power/profiles.yaml`

Create the file (daemon picks it up on next `balu-powerctl reload` or daemon restart):

```yaml
profiles:
  gaming:
    performance_level: auto
    power_profile_mode: 1
    power_cap_w: 280          # optional; omit to leave kernel default (315 W on 7900 XT)
  compute:
    performance_level: auto
    power_profile_mode: 4
    power_cap_w: 280
  display-off:
    performance_level: low
    power_profile_mode: 5
  llm-idle:
    performance_level: auto
    power_profile_mode: 5
    ollama_unload: false          # optional; true → watcher evicts loaded Ollama models
  idle:
    performance_level: auto
    power_profile_mode: 5

# Low → high. max() wins when multiple claims overlap.
priority: [idle, llm-idle, display-off, compute, gaming]

# Hardware. Auto-detected if omitted.
card: card0
```

## Ollama unload on idle

Setting `profiles.llm-idle.ollama_unload: true` tells the ollama-watcher to evict loaded models from VRAM (POST `{"model": "...", "keep_alive": 0}` to `/api/generate`) when it transitions to `llm-idle`. Saves 30–50 W at the cost of a 2–5 s cold-start on the next prompt. **Default: false.** Flip it on if you leave the machine idle overnight but rarely use Ollama.

The ollama-watcher reads this field from `/etc/balu-power/profiles.yaml` at startup. Restart the user unit after editing:

```bash
systemctl --user restart balu-power-ollama-watcher.service
```

Reload without restart:

```bash
balu-powerctl reload    # pending — or:
sudo systemctl reload balu-power.service
```

## Safe-defaults guard

`/etc/balu-power/safe-defaults.conf` defines hard upper bounds (default `max_power_cap_w = 400`). A profile exceeding these is rejected at daemon start; the daemon refuses to run. Edit `safe-defaults.conf` only if you know what you're doing.

## Non-AMD hardware

v1 hardcodes AMD RDNA3 detection. The daemon exits with ERROR if no AMD device is found under `/sys/class/drm/card*/device/vendor`. Extending to other vendors is future work (YAGNI for v1); yaml override of sysfs paths is not yet a thing.

## Multi-GPU

Only one GPU is managed per daemon. If your box has two AMD cards, set `card:` in yaml to the intended card.
```

- [ ] **Step 4: `docs/power/clients.md`**

```markdown
# BaluPower — Writing Your Own Client

The daemon is push-only. Anyone in group `balu-power` can send NDJSON over the Unix socket at `/run/balu-power.sock`.

## Protocol

One JSON object per line, UTF-8, ≤ 4 KiB.

### Claim

```json
{"v": 1, "op": "claim", "client_id": "my-client", "state": "compute", "ttl_seconds": 30}
```

- `client_id` — stable identifier unique to your client. Duplicate claims from the same client_id **replace**, not stack.
- `state` — one of `gaming`, `compute`, `display-off`, `llm-idle`, `idle`.
- `ttl_seconds` — positive integer or `null` (infinite until release). `0` is rejected.

Refresh before TTL expires if you want the claim to persist.

### Release

```json
{"v": 1, "op": "release", "client_id": "my-client"}
```

### Status

```json
{"v": 1, "op": "status"}
```

Response:

```json
{"ok": true, "current_state": "compute",
 "claims": [{"client_id":"ollama-watcher","state":"compute","expires_in_s":12}]}
```

## Priority

`gaming > compute > display-off > llm-idle > idle (fallback)`

If your client pushes `compute` while GameMode pushes `gaming`, the daemon picks `gaming`. If you care about winning a tie, push a higher-priority state — there is no `force` flag in v1.

## Example (bash)

```bash
#!/bin/bash
# Claim 'compute' for 30 s every 20 s while my workload runs.
while is_working; do
    printf '{"v":1,"op":"claim","client_id":"my-tool","state":"compute","ttl_seconds":30}\n' \
        | socat - UNIX-CONNECT:/run/balu-power.sock
    sleep 20
done
printf '{"v":1,"op":"release","client_id":"my-tool"}\n' \
    | socat - UNIX-CONNECT:/run/balu-power.sock
```

## Example (Python)

```python
import json, socket
body = {"v": 1, "op": "claim", "client_id": "my-tool",
        "state": "compute", "ttl_seconds": 30}
with socket.socket(socket.AF_UNIX) as s:
    s.connect("/run/balu-power.sock")
    s.sendall((json.dumps(body) + "\n").encode())
    print(s.recv(4096).decode())
```

## Common client patterns

- **One-shot with release**: `start` → claim with `ttl_seconds=null`; `end` → release. Used by GameMode.
- **Heartbeat**: claim with `ttl_seconds=N`, refresh every `N/2`. Lets the daemon auto-cleanup if your client crashes.
- **Edge-triggered**: only push on state transitions, not on every tick. Keeps the daemon quiet.
```

- [ ] **Step 5: Commit**

```bash
git add power/contrib/install.sh docs/power/
git commit -m "docs(power): add setup, configuration, clients guides + installer"
```

---

## Task 15: Live verification script

One-shot manual test-harness for real hardware. Not run in CI.

**Files:**
- Create: `power/tests/live/verify_7900xt.sh`
- Create: `docs/power-phase-1-verification.md`

- [ ] **Step 1: `power/tests/live/verify_7900xt.sh`**

```bash
#!/bin/bash
# Live smoke test on real RX 7900 XT hardware.
# Run AFTER install: expects daemon + CLI operational.
set -euo pipefail

DEV=/sys/class/drm/card0/device
EXPECTED=()

check() {
    local state="$1" expected_level="$2" expected_mode="$3"
    balu-powerctl claim "$state" >/dev/null
    sleep 1
    local actual_level actual_mode
    actual_level=$(cat "${DEV}/power_dpm_force_performance_level")
    actual_mode=$(awk '/\*$/{gsub(/[*: ]/,""); print $1; exit}' "${DEV}/pp_power_profile_mode" \
                  || cat "${DEV}/pp_power_profile_mode" | head -1 | awk '{print $1}')
    if [ "$actual_level" = "$expected_level" ] && [ "$actual_mode" = "$expected_mode" ]; then
        echo "  OK     $state → level=$actual_level mode=$actual_mode"
    else
        echo "  FAIL   $state → level=$actual_level (want $expected_level) mode=$actual_mode (want $expected_mode)"
        EXPECTED+=("$state")
    fi
}

echo "== balu-power live verification =="
check gaming       auto  1
check compute      auto  4
check display-off  low   5
check llm-idle     auto  5
check idle         auto  5

balu-powerctl release >/dev/null
echo
if [ ${#EXPECTED[@]} -eq 0 ]; then
    echo "All profiles applied correctly."
    exit 0
else
    echo "Failures: ${EXPECTED[*]}"
    exit 1
fi
```

Make executable:

```bash
chmod +x power/tests/live/verify_7900xt.sh
```

- [ ] **Step 2: `docs/power-phase-1-verification.md`**

```markdown
# BaluPower Phase 1 Verification

Run on real RX 7900 XT after `./power/contrib/install.sh`.

## Automated — verify_7900xt.sh

```bash
./power/tests/live/verify_7900xt.sh
```

Expected: all five profiles apply, `All profiles applied correctly.` printed.

## Manual — end-to-end scenarios

1. **Idle baseline**
   - `balu-powerctl status` → `current_state: "idle"`, no claims.
   - `radeontop` (or `nvtop`): profile indicator matches kernel default + GFX near 0.

2. **LLM compute**
   - Start an Ollama generation: `curl http://localhost:11434/api/generate -d '{"model":"qwen2.5-coder:14b","prompt":"hi"}'`.
   - Within ~10 s (watcher poll interval): `balu-powerctl status` → `compute`.
   - `journalctl -u balu-power -f` shows `transition idle → compute`.
   - After generation ends + 15 s TTL: state → `llm-idle`.

3. **Display off**
   - On X11: `xset dpms force off`. On Wayland: lock/sleep per compositor.
   - Wait for compositor to set IdleHint=true (KDE ~3 min default; tune via System Settings).
   - `balu-powerctl status` → `display-off`.
   - Move mouse → returns to `idle` (or whatever watcher's most recent claim yields).

4. **Gaming**
   - Launch a Steam title with `gamemoderun %command%` in launch options.
   - `balu-powerctl status` → `gaming`.
   - Quit game → back to `idle`.

5. **Concurrent compute + display-off**
   - Run Ollama prompt while monitor is asleep.
   - `balu-powerctl status` → `compute` (priority 3 > 2 for display-off).
   - Wait for generation to end → `display-off`.
   - Wake display → `idle`.

6. **Crash recovery**
   - `sudo systemctl kill -s KILL balu-power`.
   - sysfs values reset to kernel default (`auto`, mode `0`) via the reset hook.
   - systemd restarts the daemon; `balu-powerctl status` works again within ~2 s.

## Pass criteria

- All 5 automated profile checks `OK`.
- Scenarios 2–5 transition correctly within 15 s of trigger (poll interval).
- Scenario 6: sysfs reset is observable, daemon comes back.

## Failure playbook

- `balu-powerctl status` hangs → socket perms. `ls -l /run/balu-power.sock`; user must be in `balu-power` group.
- `current_state` never leaves `idle` when Ollama is busy → check `systemctl --user status balu-power-ollama-watcher`, `journalctl --user -u balu-power-ollama-watcher`.
- `display-off` never triggers → `busctl --user get-property org.freedesktop.login1 /org/freedesktop/login1/session/self org.freedesktop.login1.Session IdleHint` should report `true` when idle. If it's always `false`, your compositor is not setting IdleHint — check compositor docs (KDE: Power Management; swayidle for sway).
- sysfs write errors in journald → `amdgpu.ppfeaturemask=0xffffffff` may be missing from `GRUB_CMDLINE_LINUX`. Add and regenerate GRUB.
```

- [ ] **Step 3: Commit**

```bash
git add power/tests/live/ docs/power-phase-1-verification.md
git commit -m "test(power): add live verify_7900xt.sh + phase-1 checklist"
```

---

## Task 16: End-of-phase verification

After all previous tasks pass, run the full pytest sweep and a lint pass. Document any real-hardware smoke-test outcomes in `docs/power-phase-1-verification.md` itself (Sven runs this manually on his 7900 XT).

**Files:**
- Modify: `docs/power-phase-1-verification.md` (append results section)

- [ ] **Step 1: Full unit + integration sweep**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/pytest power/tests -v
```

Expected: all tests pass (unit + integration). DBus display-watcher test skips if `python-dbusmock` absent — document in output.

- [ ] **Step 2: Lint sweep**

```bash
.venv/bin/ruff check power/
.venv/bin/ruff format --check power/
```

Expected: no issues.

- [ ] **Step 3: Run install script on target host**

```bash
./power/contrib/install.sh
# log out + in
balu-powerctl status
```

Expected: `{"ok": true, "current_state": "idle", "claims": []}`.

- [ ] **Step 4: Run live verification script on 7900 XT**

```bash
./power/tests/live/verify_7900xt.sh
```

Expected: `All profiles applied correctly.`

- [ ] **Step 5: Append results to verification doc**

Example stub for `docs/power-phase-1-verification.md`:

```markdown
## Results

- **Date:** YYYY-MM-DD
- **Kernel:** 6.X.Y
- **ROCm:** 6.Z
- **GPU:** RX 7900 XT
- **All pytest:** PASS (N unit, M integration)
- **Live verify:** PASS
- **End-to-end scenarios:** 1/2/3/4/5/6 PASS / FAIL: [notes]

## Known issues

[none / list]
```

- [ ] **Step 6: Commit**

```bash
git add docs/power-phase-1-verification.md
git commit -m "docs(power): record phase-1 verification results on 7900 XT"
```

---

## Done
