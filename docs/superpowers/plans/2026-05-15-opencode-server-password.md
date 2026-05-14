# OpenCode Server Password Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Secure the embedded OpenCode server with a per-installation password so it no longer accepts unauthenticated requests, even when reachable through the nginx LAN proxy or shared with another local user.

**Architecture:** Generate a 32-byte URL-safe password on first plugin start, persist it as `<data_dir>/runtime.password` (mode 0600), inject it as `OPENCODE_SERVER_PASSWORD` into the `opencode serve` env, and present it as `Authorization: Basic base64("opencode:<pw>")` on every internal HTTP call (health probes + `OpencodeClient`). Expose the password to authenticated BaluHost API consumers via a new `/runtime/credentials` endpoint so the standalone `opencode` CLI can attach.

**Tech Stack:** Python 3.12 · httpx (sync `BasicAuth`) · pytest + respx · FastAPI · existing plugin services in `plugin/services/`.

**Verified upstream behaviour (opencode v1.14.50, live probe 2026-05-15):**
- env var `OPENCODE_SERVER_PASSWORD` enables Basic Auth on **all** endpoints (incl. `/global/health`).
- Realm: `Basic realm="Secure Area"`.
- Username is hardcoded to `opencode`; only `Authorization: Basic base64("opencode:<pw>")` returns 200, every other scheme returns 401.

---

## File Structure

| Status | Path | Responsibility |
|---|---|---|
| Create | `plugin/services/runtime_password.py` | Generate / load / persist the OpenCode server password (mode 0600). |
| Modify | `plugin/services/opencode_client.py` | Accept `password` and use `httpx.BasicAuth("opencode", password)`. |
| Modify | `plugin/services/opencode_runtime.py` | Thread `password` through `start_server` / `start_or_attach_server`; inject as env; use Basic Auth in health probes. |
| Modify | `plugin/__init__.py` | Bootstrap loads/creates the password before spawn; passes it to runtime + client. |
| Modify | `plugin/schemas.py` | Add `RuntimeCredentialsResponse` model. |
| Modify | `plugin/routes.py` | Add `GET /runtime/credentials`. |
| Create | `plugin/tests/test_runtime_password.py` | Unit tests for the password lifecycle module. |
| Modify | `plugin/tests/test_opencode_client.py` | Cover Basic-Auth header injection. |
| Modify | `plugin/tests/test_opencode_runtime.py` | Cover `OPENCODE_SERVER_PASSWORD` env injection + auth on health probes. |
| Modify | `plugin/tests/test_routes_phase2.py` *(or new `test_routes_runtime.py`)* | Cover the `/runtime/credentials` endpoint. |
| Modify | `docs/phase-opencode-verification.md` | Replace the "TODO" section with a "Done" note documenting Basic Auth + the orphan-server migration step. |

---

## Task 1: Runtime password lifecycle module

**Files:**
- Create: `plugin/services/runtime_password.py`
- Test:   `plugin/tests/test_runtime_password.py`

- [ ] **Step 1.1: Write the failing tests**

Create `plugin/tests/test_runtime_password.py`:

```python
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
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `pytest plugin/tests/test_runtime_password.py -v`
Expected: `ImportError: cannot import name 'load_or_create_password' from 'plugin.services.runtime_password'` (module does not exist yet).

- [ ] **Step 1.3: Implement the module**

Create `plugin/services/runtime_password.py`:

```python
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
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `pytest plugin/tests/test_runtime_password.py -v`
Expected: all 6 tests pass.

- [ ] **Step 1.5: Commit**

```bash
git add plugin/services/runtime_password.py plugin/tests/test_runtime_password.py
git commit -m "feat(runtime): persist OpenCode server password under data_dir"
```

---

## Task 2: OpencodeClient sends Basic Auth

**Files:**
- Modify: `plugin/services/opencode_client.py:15-30`
- Modify: `plugin/tests/test_opencode_client.py`

- [ ] **Step 2.1: Write the failing tests**

Append to `plugin/tests/test_opencode_client.py`:

```python
import base64


@pytest.mark.asyncio
async def test_health_sends_basic_auth_header_when_password_set():
    async with OpencodeClient("http://127.0.0.1:4096", password="secret-pw") as client:
        with respx.mock(base_url="http://127.0.0.1:4096") as mock:
            route = mock.get("/global/health").mock(
                return_value=httpx.Response(200, json={})
            )
            await client.health()
            expected = b"Basic " + base64.b64encode(b"opencode:secret-pw")
            assert route.calls.last.request.headers["authorization"].encode() == expected


@pytest.mark.asyncio
async def test_no_authorization_header_when_password_omitted():
    async with OpencodeClient("http://127.0.0.1:4096") as client:
        with respx.mock(base_url="http://127.0.0.1:4096") as mock:
            route = mock.get("/global/health").mock(
                return_value=httpx.Response(200, json={})
            )
            await client.health()
            assert "authorization" not in (
                k.lower() for k in route.calls.last.request.headers.keys()
            )


@pytest.mark.asyncio
async def test_create_session_sends_basic_auth_header():
    async with OpencodeClient("http://127.0.0.1:4096", password="pw2") as client:
        with respx.mock(base_url="http://127.0.0.1:4096") as mock:
            route = mock.post("/session").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "id": "ses_abc",
                        "time": {"created": 0, "updated": 0},
                        "version": "1.14.50",
                    },
                )
            )
            await client.create_session()
            expected = b"Basic " + base64.b64encode(b"opencode:pw2")
            assert route.calls.last.request.headers["authorization"].encode() == expected
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `pytest plugin/tests/test_opencode_client.py -v -k basic_auth or no_authorization`
Expected: `TypeError: OpencodeClient.__init__() got an unexpected keyword argument 'password'`.

- [ ] **Step 2.3: Add the `password` parameter to OpencodeClient**

Replace the constructor block in `plugin/services/opencode_client.py` (lines 15-30) with:

```python
class OpencodeClient:
    def __init__(
        self,
        base_url: str,
        *,
        password: str | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        auth: httpx.Auth | None = (
            httpx.BasicAuth("opencode", password) if password else None
        )
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            auth=auth,
        )
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `pytest plugin/tests/test_opencode_client.py -v`
Expected: all tests pass, including the 6 pre-existing ones.

- [ ] **Step 2.5: Commit**

```bash
git add plugin/services/opencode_client.py plugin/tests/test_opencode_client.py
git commit -m "feat(opencode_client): send Basic Auth header when password is set"
```

---

## Task 3: opencode_runtime threads password to env and probes

**Files:**
- Modify: `plugin/services/opencode_runtime.py:139-180` (`start_server`)
- Modify: `plugin/services/opencode_runtime.py:209-256` (`_wait_for_health`, `_probe_health`)
- Modify: `plugin/services/opencode_runtime.py:259-313` (`start_or_attach_server`)
- Modify: `plugin/tests/test_opencode_runtime.py`

- [ ] **Step 3.1: Write the failing test for env injection**

Append to `plugin/tests/test_opencode_runtime.py`:

```python
@pytest.mark.asyncio
@pytest.mark.skipif(not os.path.exists("/proc/self/environ"), reason="Linux /proc not available")
async def test_start_server_passes_password_env(tmp_path, monkeypatch):
    fake = tmp_path / "runtime" / "opencode-linux-x86_64"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(0o755)
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    log = tmp_path / "opencode.log"

    monkeypatch.setattr(rt, "_wait_for_health", _stub_wait_healthy)
    monkeypatch.setattr(rt, "_read_port_from_log", lambda *a, **kw: 4096)

    handle = await rt.start_server(
        binary=fake,
        config_dir=cfg_dir,
        log_path=log,
        port=4096,
        ready_timeout=2.0,
        password="super-secret-pw",
    )
    try:
        await asyncio.sleep(0.1)
        import pathlib

        env_data = pathlib.Path(f"/proc/{handle.pid}/environ").read_bytes().split(b"\x00")
        env_dict = dict(e.decode().split("=", 1) for e in env_data if b"=" in e)
        assert env_dict.get("OPENCODE_SERVER_PASSWORD") == "super-secret-pw"
    finally:
        await rt.stop_server(handle)


@pytest.mark.asyncio
async def test_start_server_omits_password_env_when_none(tmp_path, monkeypatch):
    """When password is None, OPENCODE_SERVER_PASSWORD must NOT be set."""
    fake = tmp_path / "runtime" / "opencode-linux-x86_64"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(0o755)
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    log = tmp_path / "opencode.log"

    monkeypatch.setattr(rt, "_wait_for_health", _stub_wait_healthy)
    monkeypatch.setattr(rt, "_read_port_from_log", lambda *a, **kw: 4096)
    monkeypatch.delenv("OPENCODE_SERVER_PASSWORD", raising=False)

    handle = await rt.start_server(
        binary=fake, config_dir=cfg_dir, log_path=log, port=4096, ready_timeout=2.0
    )
    try:
        await asyncio.sleep(0.1)
        import pathlib

        environ_file = pathlib.Path(f"/proc/{handle.pid}/environ")
        if environ_file.exists():
            env_data = environ_file.read_bytes().split(b"\x00")
            env_dict = dict(e.decode().split("=", 1) for e in env_data if b"=" in e)
            assert "OPENCODE_SERVER_PASSWORD" not in env_dict
    finally:
        await rt.stop_server(handle)
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `pytest plugin/tests/test_opencode_runtime.py::test_start_server_passes_password_env -v`
Expected: `TypeError: start_server() got an unexpected keyword argument 'password'`.

- [ ] **Step 3.3: Add the `password` parameter to `start_server`**

In `plugin/services/opencode_runtime.py`, replace the `start_server` signature and env block. Original lines 139-167:

```python
async def start_server(
    *,
    binary: Path,
    config_dir: Path,
    log_path: Path,
    port: int = 4096,
    hostname: str = "127.0.0.1",
    ready_timeout: float = 15.0,
) -> ServerHandle:
    ...
    env = {**os.environ, "OPENCODE_CONFIG_DIR": str(config_dir)}
```

New version:

```python
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
    healthy = await _wait_for_health(hostname, actual_port, timeout=ready_timeout, password=password)
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
```

- [ ] **Step 3.4: Add `password` to `_wait_for_health` and `_probe_health`**

Replace `_wait_for_health` and `_probe_health` (lines 209-256) with:

```python
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
```

- [ ] **Step 3.5: Add `password` to `start_or_attach_server`**

Replace the signature and the relevant calls in `start_or_attach_server` (lines 259-313):

```python
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
```

- [ ] **Step 3.6: Run runtime tests to verify they pass**

Run: `pytest plugin/tests/test_opencode_runtime.py -v`
Expected: all tests pass (new + existing 14 tests).

- [ ] **Step 3.7: Commit**

```bash
git add plugin/services/opencode_runtime.py plugin/tests/test_opencode_runtime.py
git commit -m "feat(opencode_runtime): plumb OpenCode server password through spawn & probes"
```

---

## Task 4: Plugin bootstrap loads and uses the password

**Files:**
- Modify: `plugin/__init__.py:75-126` (`on_startup`)
- Modify: `plugin/deps.py` (singleton storage for password, optional)
- Modify: `plugin/tests/test_plugin_lifecycle.py`

- [ ] **Step 4.1: Inspect the current `deps.py` to understand singletons**

Run: `grep -n "set_singletons\|password\|opencode" plugin/deps.py`

Decide based on output: if `deps.py` already exposes a getter for the opencode password (it does not at the time of plan writing), reuse it. Otherwise add a private module-level variable + getter so route handlers can read the password later without re-loading the file.

- [ ] **Step 4.2: Write a failing test for the password-stored singleton**

Append to `plugin/tests/test_plugin_lifecycle.py` (or create `plugin/tests/test_deps_password.py` if `test_plugin_lifecycle.py` has no fixture for `deps.py` state):

```python
from plugin.deps import get_opencode_password, set_opencode_password, clear_opencode_password


def test_opencode_password_singleton_roundtrip():
    set_opencode_password("hello-pw")
    assert get_opencode_password() == "hello-pw"
    clear_opencode_password()
    with pytest.raises(RuntimeError):
        get_opencode_password()
```

- [ ] **Step 4.3: Run test to verify it fails**

Run: `pytest plugin/tests/test_plugin_lifecycle.py -v -k opencode_password`
Expected: `ImportError` for `set_opencode_password`.

- [ ] **Step 4.4: Add the password singleton to `plugin/deps.py`**

Insert next to the existing `_opencode_client` singleton:

```python
_opencode_password: str | None = None


def set_opencode_password(password: str) -> None:
    global _opencode_password
    _opencode_password = password


def get_opencode_password() -> str:
    if _opencode_password is None:
        raise RuntimeError("opencode password not initialized")
    return _opencode_password


def clear_opencode_password() -> None:
    global _opencode_password
    _opencode_password = None
```

Also wire `clear_opencode_password()` into the existing `clear_singletons()` so the autouse fixture in `tests/conftest.py` resets it between tests. Locate the body of `clear_singletons()` in `deps.py` and append the call.

- [ ] **Step 4.5: Modify `on_startup` to load and use the password**

In `plugin/__init__.py`, replace lines 101-125 with:

```python
        from .deps import set_opencode, set_opencode_password
        from .services.opencode_client import OpencodeClient
        from .services.opencode_config import write_opencode_config
        from .services.opencode_runtime import ensure_binary, start_or_attach_server
        from .services.runtime_password import load_or_create_password

        # Phase A: treat as allowed; Phase B wires the real BaluHost permission check.
        file_write_allowed = True

        opencode_binary = await ensure_binary(data_dir)
        opencode_cfg_path = write_opencode_config(
            data_dir, self._config, file_write_allowed=file_write_allowed
        )
        opencode_log_path = data_dir / "opencode.log"
        opencode_password = load_or_create_password(data_dir)
        set_opencode_password(opencode_password)
        handle = await start_or_attach_server(
            binary=opencode_binary,
            config_dir=opencode_cfg_path.parent,  # OPENCODE_CONFIG_DIR
            log_path=opencode_log_path,
            lock_path=data_dir / "runtime.lock",
            port=self._config.opencode_port,
            ready_timeout=20.0,
            password=opencode_password,
        )
        opencode_client = OpencodeClient(
            f"http://127.0.0.1:{handle.port}", password=opencode_password
        )
        set_opencode(handle, opencode_client)
        self._opencode_handle = handle
        self._opencode_client = opencode_client
```

- [ ] **Step 4.6: Run targeted tests**

Run: `pytest plugin/tests/test_plugin_lifecycle.py -v`
Expected: existing lifecycle tests still pass + the new `opencode_password_singleton_roundtrip` test passes.

- [ ] **Step 4.7: Commit**

```bash
git add plugin/__init__.py plugin/deps.py plugin/tests/test_plugin_lifecycle.py
git commit -m "feat(plugin): bootstrap loads runtime password and threads it into runtime+client"
```

---

## Task 5: `GET /runtime/credentials` endpoint

**Files:**
- Modify: `plugin/schemas.py` (new model)
- Modify: `plugin/routes.py:306-326` (next to existing `/runtime/...` endpoints)
- Create: `plugin/tests/test_routes_runtime_credentials.py`

- [ ] **Step 5.1: Inspect existing runtime routes**

Run: `sed -n '300,330p' plugin/routes.py`

This shows the existing `/runtime/status` and `/runtime/restart` handlers so the new endpoint can match their style (tags, response_model, dependency injection patterns).

- [ ] **Step 5.2: Write the failing route test**

Create `plugin/tests/test_routes_runtime_credentials.py`:

```python
"""Tests for GET /runtime/credentials — exposes the OpenCode Basic Auth password."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from plugin.deps import set_opencode_password
from plugin.routes import build_router


@pytest.fixture
def app_with_router() -> FastAPI:
    app = FastAPI()
    app.include_router(build_router(), prefix="/api/plugins/balu_code")
    return app


@pytest.mark.asyncio
async def test_runtime_credentials_returns_username_and_password(app_with_router):
    set_opencode_password("test-pw-xyz")
    transport = ASGITransport(app=app_with_router)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/plugins/balu_code/runtime/credentials")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"username": "opencode", "password": "test-pw-xyz"}


@pytest.mark.asyncio
async def test_runtime_credentials_returns_503_when_not_initialised(app_with_router):
    # No set_opencode_password call — singleton is cleared by autouse fixture.
    transport = ASGITransport(app=app_with_router)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/plugins/balu_code/runtime/credentials")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_runtime_credentials_requires_authentication(app_with_router):
    """A 401 from get_current_user must keep the password from being returned."""
    from fastapi import HTTPException, status

    from app.api.deps import get_current_user

    async def _denied():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    app_with_router.dependency_overrides[get_current_user] = _denied
    set_opencode_password("must-not-leak")
    transport = ASGITransport(app=app_with_router)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/plugins/balu_code/runtime/credentials")
    assert resp.status_code == 401
    assert "must-not-leak" not in resp.text
```

- [ ] **Step 5.3: Run test to verify it fails**

Run: `pytest plugin/tests/test_routes_runtime_credentials.py -v`
Expected: 404 (route does not exist).

- [ ] **Step 5.4: Add the response schema**

Append to `plugin/schemas.py`:

```python
class RuntimeCredentialsResponse(BaseModel):
    """Basic-Auth credentials for the embedded OpenCode server.

    Returned for callers who need to attach to the local server with the
    standalone ``opencode`` CLI or a browser:
        OPENCODE_SERVER_PASSWORD=<password> opencode attach http://127.0.0.1:<port>
    """

    username: str
    password: str
```

- [ ] **Step 5.5: Add the route handler**

In `plugin/routes.py`, inside `build_router()`, add a handler near the existing `/runtime/status` endpoint (around line 306):

```python
    @router.get(
        "/runtime/credentials",
        response_model=RuntimeCredentialsResponse,
        tags=["balu_code"],
    )
    def runtime_credentials(
        _user: UserPublic = Depends(get_current_user),
    ) -> RuntimeCredentialsResponse:
        try:
            password = get_opencode_password()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="opencode runtime not initialized",
            ) from exc
        return RuntimeCredentialsResponse(username="opencode", password=password)
```

At the top of `routes.py`, ensure the imports include:

```python
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.schemas.user import UserPublic

from .deps import get_opencode_password
from .schemas import RuntimeCredentialsResponse
```

(merge with existing import lines; do not duplicate — `Depends`, `get_current_user`, and `UserPublic` are already imported at the top of `routes.py`).

**Why auth is required here:** unlike `/runtime/status` (metadata only), this endpoint returns the OpenCode Basic Auth password in the response body. Anyone who can reach the plugin's port without a BaluHost JWT would obtain the credential. Adding the `Depends(get_current_user)` matches the pattern used by `/config`, `/logs`, `/projects`, etc. The pre-existing `/runtime/status` and `/runtime/restart` skip auth because they are metadata-only; tightening those is out of scope for this plan and tracked separately.

- [ ] **Step 5.6: Run tests to verify they pass**

Run: `pytest plugin/tests/test_routes_runtime_credentials.py -v`
Expected: both tests pass.

- [ ] **Step 5.7: Commit**

```bash
git add plugin/schemas.py plugin/routes.py plugin/tests/test_routes_runtime_credentials.py
git commit -m "feat(routes): add GET /runtime/credentials for OpenCode Basic Auth password"
```

---

## Task 6: Documentation + migration note

**Files:**
- Modify: `docs/phase-opencode-verification.md:170-196`

- [ ] **Step 6.1: Replace the TODO section with a Done note**

Open `docs/phase-opencode-verification.md` and replace lines 170-196 with:

```markdown
## opencode server password (done in 0.3.0)

opencode logs `Warning: OPENCODE_SERVER_PASSWORD is not set; server is
unsecured.` when started without a password. The plugin now sets one:

- On first start, ``plugin/services/runtime_password.py`` generates a
  32-byte URL-safe value and persists it as
  ``<data_dir>/runtime.password`` (mode 0600). Subsequent starts reload
  the same value.
- ``plugin/services/opencode_runtime.py`` injects the password as
  ``OPENCODE_SERVER_PASSWORD`` into the spawned process env, and every
  internal health probe sends ``Authorization: Basic
  base64("opencode:<password>")``.
- ``plugin/services/opencode_client.py`` does the same for ``/session``
  and ``/session/{id}/message`` calls.
- Authenticated BaluHost API consumers can fetch the password from
  ``GET /api/plugins/balu_code/runtime/credentials`` (response:
  ``{"username": "opencode", "password": "..."}``). This is how the
  standalone CLI / browser usage works:

      OPENCODE_SERVER_PASSWORD=$(curl -s ... /credentials | jq -r .password) \
        opencode attach http://127.0.0.1:4096

### Upstream auth contract (verified on v1.14.50)

- ``WWW-Authenticate: Basic realm="Secure Area"`` on every 401 response.
- Hardcoded username ``opencode`` — any other user returns 401 even
  with the right password.
- ``/global/health`` is **also** behind the auth wall; an unauthenticated
  probe returns 401, which is treated as "not healthy" by the runtime
  watchdog.

### Migration: existing orphan server

A baluhost-backend that was running before this change spawned a child
opencode process **without** ``OPENCODE_SERVER_PASSWORD``. After
upgrading, restart the backend so the new code path takes over:

```bash
sudo pkill -f 'opencode-linux-x86_64 serve'
sudo systemctl restart baluhost-backend
```

The next plugin boot spawns a fresh opencode process with the persisted
password.
```

- [ ] **Step 6.2: Commit**

```bash
git add docs/phase-opencode-verification.md
git commit -m "docs(opencode): document Basic Auth contract and migration"
```

---

## Task 7: Full suite + live smoke test

- [ ] **Step 7.1: Run the full plugin test suite**

Run: `pytest plugin/tests -v --maxfail=5`
Expected: every test passes, no warnings about un-awaited coroutines or unclosed httpx clients.

- [ ] **Step 7.2: Kill the orphan opencode and restart baluhost-backend**

Run:

```bash
sudo pkill -f 'opencode-linux-x86_64 serve' || true
sudo systemctl restart baluhost-backend
```

Wait ~10s for the new plugin boot, then check:

```bash
sleep 10
ls -la ~/.local/share/balu-code/runtime.password
test "$(stat -c %a ~/.local/share/balu-code/runtime.password)" = "600" && echo "mode ok"
```

Expected: file exists with mode 600.

- [ ] **Step 7.3: Verify the password is enforced end-to-end**

Run:

```bash
PW=$(cat ~/.local/share/balu-code/runtime.password)
echo "no auth ->" $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4096/global/health)
echo "with auth ->" $(curl -s -o /dev/null -w '%{http_code}' -u "opencode:$PW" http://127.0.0.1:4096/global/health)
```

Expected:
- `no auth -> 401`
- `with auth -> 200`

- [ ] **Step 7.4: Verify the plugin can still drive opencode**

Hit the plugin health endpoint (already proxied through nginx):

```bash
curl -sk --resolve baluhost.local:443:127.0.0.1 \
  https://baluhost.local/api/plugins/balu_code/health
```

Expected: `{"status":"ok","plugin":"balu_code","version":"0.2.0"}` (still works because the plugin uses the password internally).

- [ ] **Step 7.5: Verify the `/runtime/credentials` endpoint**

```bash
curl -sk --resolve baluhost.local:443:127.0.0.1 \
  https://baluhost.local/api/plugins/balu_code/runtime/credentials
```

Expected: `{"username":"opencode","password":"<same value as in ~/.local/share/balu-code/runtime.password>"}`.

- [ ] **Step 7.6: Optional — relax the nginx LAN-only ACL**

If `:8443` should now be reachable from outside the LAN, edit
`/opt/baluhost/deploy/nginx/opencode-https.conf` and remove (or widen)
the `allow .../deny all` block. Re-run
`sudo /opt/baluhost/deploy/ssl/setup-opencode-proxy.sh` to redeploy.
Skip this step if the LAN-only posture should stay (defense-in-depth).

- [ ] **Step 7.7: Update memory**

After successful smoke test, write a memory note documenting that the
OpenCode Basic-Auth contract is "opencode" / value-of-`runtime.password`,
since this fact will be needed every time someone debugs `:4096` access.

---

## Out of scope

- Rotating the password without manual file deletion. (Acceptable for v0.3.0
  — sven can just `rm ~/.local/share/balu-code/runtime.password` and restart
  the plugin to force a re-generate.)
- Distinct passwords per BaluHost user. The shared password is fine for a
  single-tenant homelab; multi-user separation belongs in v0.4.0 if at all.
- Surfacing the password in the BaluHost web UI Runtime tab. Frontend
  work tracked separately under the v0.3.0 chat-UI rebuild.
