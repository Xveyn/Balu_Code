# Balu Code Phase 5a — CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a working `balu-code` CLI with `auth`, `init`, `models`, `index`, and an interactive `chat` REPL with Rich streaming, tool-call display, and approval prompts with persistent per-project permission tracking.

**Architecture:** asyncio + Rich. Every Typer command is synchronous and calls `asyncio.run()` internally. The WS client is a thin `async def` wrapper over `websockets`. HTTP uses `httpx`. Config/credentials/permissions live in `~/.config/balu-code/` as YAML files backed by Pydantic models. Approval lookup priority: `--yolo` > `.balucode.yaml` `allow_*` > `permissions.yaml` > interactive prompt.

**Tech Stack:** Python 3.11+, `typer>=0.12` (existing), `websockets>=13`, `rich>=13`, `pyyaml>=6`, `httpx` (existing in project via web_fetch), `balu-code-shared` (existing), `respx>=0.21` (test only), `pytest-asyncio` (existing)

---

## File Map

**New files:**
```
cli/src/balu_code_cli/
  config/
    __init__.py
    paths.py           # XDG-aware path constants for ~/.config/balu-code/
    loader.py          # AppConfig + Credentials Pydantic models + read/write
    permissions.py     # PermissionsStore Pydantic model + read/write/lookup
    balucode_yaml.py   # BaluCodeYaml model + walk-up search + is_tool_allowed()
  client/
    __init__.py
    http.py            # BaluCodeHttpClient (httpx wrapper, auth header)
    ws.py              # BaluCodeWS + connect() async context manager
  commands/
    __init__.py
    auth.py            # auth login + auth status
    init.py            # init wizard
    models.py          # models list
    index.py           # index + poll loop
    chat.py            # chat REPL + event dispatch + approval flow

cli/tests/
  test_config_loader.py
  test_config_permissions.py
  test_config_balucode_yaml.py
  test_client_http.py
  test_client_ws.py
  test_cmd_auth.py
  test_cmd_init.py
  test_cmd_models.py
  test_cmd_index.py
  test_cmd_chat.py
```

**Modified files:**
```
cli/pyproject.toml       # add websockets, rich, pyyaml deps; respx to dev
cli/src/balu_code_cli/__main__.py   # register auth group + all subcommands
```

---

## Task 1: Add dependencies & create package skeletons

**Files:**
- Modify: `cli/pyproject.toml`
- Create: `cli/src/balu_code_cli/config/__init__.py`
- Create: `cli/src/balu_code_cli/client/__init__.py`
- Create: `cli/src/balu_code_cli/commands/__init__.py`

- [ ] **Step 1: Update `cli/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "balu-code-cli"
version = "0.1.0"
description = "Terminal client for the Balu Code self-hosted coding agent."
readme = "../README.md"
license = { file = "../LICENSE" }
requires-python = ">=3.11"
authors = [{ name = "Xveyn" }]
dependencies = [
  "typer>=0.12",
  "balu-code-shared",
  "websockets>=13",
  "rich>=13",
  "pyyaml>=6",
  "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.24",
  "respx>=0.21",
  "ruff>=0.4",
]

[project.scripts]
balu-code = "balu_code_cli.__main__:app"

[tool.hatch.build.targets.wheel]
packages = ["src/balu_code_cli"]
```

- [ ] **Step 2: Create empty `__init__.py` files**

```bash
touch cli/src/balu_code_cli/config/__init__.py \
      cli/src/balu_code_cli/client/__init__.py \
      cli/src/balu_code_cli/commands/__init__.py
```

- [ ] **Step 3: Sync dependencies**

```bash
uv sync
```

Expected: resolves without errors, websockets/rich/pyyaml installed.

- [ ] **Step 4: Verify existing tests still pass**

```bash
uv run pytest cli/tests/ -q
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add cli/pyproject.toml cli/src/balu_code_cli/config/__init__.py \
        cli/src/balu_code_cli/client/__init__.py \
        cli/src/balu_code_cli/commands/__init__.py
git commit -m "build(cli): add websockets/rich/pyyaml deps + package skeletons"
```

---

## Task 2: `config/paths.py` — XDG path constants

**Files:**
- Create: `cli/src/balu_code_cli/config/paths.py`
- Create: `cli/tests/test_config_loader.py` (starts here, grows in Task 3)

- [ ] **Step 1: Write the failing test**

`cli/tests/test_config_loader.py`:
```python
"""Tests for config/loader.py and config/paths.py."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_config_dir_uses_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Re-import after env change to pick up new value
    import importlib
    import balu_code_cli.config.paths as paths_mod
    importlib.reload(paths_mod)
    assert paths_mod.config_dir() == tmp_path / "balu-code"


def test_config_dir_defaults_to_home_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib
    import balu_code_cli.config.paths as paths_mod
    importlib.reload(paths_mod)
    assert paths_mod.config_dir() == tmp_path / ".config" / "balu-code"
```

- [ ] **Step 2: Run test — verify it fails**

```bash
uv run pytest cli/tests/test_config_loader.py -v
```

Expected: `ModuleNotFoundError: No module named 'balu_code_cli.config.paths'`

- [ ] **Step 3: Implement `config/paths.py`**

```python
"""XDG-aware path constants for ~/.config/balu-code/."""

from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "balu-code"


def config_yaml() -> Path:
    return config_dir() / "config.yaml"


def credentials_yaml() -> Path:
    return config_dir() / "credentials.yaml"


def permissions_yaml() -> Path:
    return config_dir() / "permissions.yaml"


__all__ = ["config_dir", "config_yaml", "credentials_yaml", "permissions_yaml"]
```

- [ ] **Step 4: Run test — verify it passes**

```bash
uv run pytest cli/tests/test_config_loader.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add cli/src/balu_code_cli/config/paths.py cli/tests/test_config_loader.py
git commit -m "feat(cli): add config/paths.py XDG path helpers"
```

---

## Task 3: `config/loader.py` — AppConfig + Credentials

**Files:**
- Create: `cli/src/balu_code_cli/config/loader.py`
- Modify: `cli/tests/test_config_loader.py`

- [ ] **Step 1: Append failing tests**

Add to `cli/tests/test_config_loader.py`:
```python
from balu_code_cli.config.loader import (
    AppConfig,
    Credentials,
    ServerCredentials,
    load_config,
    load_credentials,
    save_config,
    save_credentials,
)


def test_load_config_returns_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.server_url == ""
    assert cfg.default_project_id is None


def test_save_and_load_config_round_trips(tmp_path):
    path = tmp_path / "config.yaml"
    cfg = AppConfig(server_url="https://balu.example.com", default_project_id=42)
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.server_url == "https://balu.example.com"
    assert loaded.default_project_id == 42


def test_load_credentials_returns_empty_when_file_missing(tmp_path):
    creds = load_credentials(tmp_path / "credentials.yaml")
    assert creds.servers == {}


def test_save_credentials_sets_mode_0600(tmp_path):
    path = tmp_path / "credentials.yaml"
    creds = Credentials(servers={"https://balu.example.com": ServerCredentials(api_key="bc_abc123")})
    save_credentials(creds, path)
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_save_and_load_credentials_round_trips(tmp_path):
    path = tmp_path / "credentials.yaml"
    creds = Credentials(servers={"https://balu.example.com": ServerCredentials(api_key="bc_xyz")})
    save_credentials(creds, path)
    loaded = load_credentials(path)
    assert loaded.servers["https://balu.example.com"].api_key == "bc_xyz"
```

- [ ] **Step 2: Run — verify they fail**

```bash
uv run pytest cli/tests/test_config_loader.py -v
```

Expected: `ImportError` on the new imports.

- [ ] **Step 3: Implement `config/loader.py`**

```python
"""AppConfig + Credentials read/write."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel

from balu_code_cli.config.paths import config_yaml, credentials_yaml


class AppConfig(BaseModel):
    server_url: str = ""
    default_project_id: int | None = None


class ServerCredentials(BaseModel):
    api_key: str


class Credentials(BaseModel):
    servers: dict[str, ServerCredentials] = {}


def load_config(path: Path | None = None) -> AppConfig:
    p = path or config_yaml()
    if not p.exists():
        return AppConfig()
    data = yaml.safe_load(p.read_text()) or {}
    return AppConfig.model_validate(data)


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    p = path or config_yaml()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(cfg.model_dump(exclude_none=True)))


def load_credentials(path: Path | None = None) -> Credentials:
    p = path or credentials_yaml()
    if not p.exists():
        return Credentials()
    data = yaml.safe_load(p.read_text()) or {}
    return Credentials.model_validate(data)


def save_credentials(creds: Credentials, path: Path | None = None) -> None:
    p = path or credentials_yaml()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(creds.model_dump()))
    os.chmod(p, 0o600)


__all__ = [
    "AppConfig",
    "Credentials",
    "ServerCredentials",
    "load_config",
    "load_credentials",
    "save_config",
    "save_credentials",
]
```

- [ ] **Step 4: Run — verify all pass**

```bash
uv run pytest cli/tests/test_config_loader.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add cli/src/balu_code_cli/config/loader.py cli/tests/test_config_loader.py
git commit -m "feat(cli): add config/loader.py (AppConfig + Credentials)"
```

---

## Task 4: `config/permissions.py` — PermissionsStore

**Files:**
- Create: `cli/src/balu_code_cli/config/permissions.py`
- Create: `cli/tests/test_config_permissions.py`

- [ ] **Step 1: Write failing tests**

`cli/tests/test_config_permissions.py`:
```python
"""Tests for config/permissions.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from balu_code_cli.config.permissions import (
    PermissionsStore,
    load_permissions,
    save_permissions,
)

SERVER = "https://balu.example.com"
PID = 42


def test_lookup_returns_none_when_no_entry():
    store = PermissionsStore()
    assert store.lookup(SERVER, PID, "write_file") is None


def test_set_and_lookup_round_trips():
    store = PermissionsStore()
    store.set(SERVER, PID, "write_file", True)
    assert store.lookup(SERVER, PID, "write_file") is True


def test_set_false_and_lookup():
    store = PermissionsStore()
    store.set(SERVER, PID, "run_bash", False)
    assert store.lookup(SERVER, PID, "run_bash") is False


def test_lookup_missing_tool_returns_none():
    store = PermissionsStore()
    store.set(SERVER, PID, "write_file", True)
    assert store.lookup(SERVER, PID, "run_bash") is None


def test_load_returns_empty_when_file_missing(tmp_path):
    store = load_permissions(tmp_path / "permissions.yaml")
    assert store.permissions == {}


def test_save_and_load_round_trips(tmp_path):
    path = tmp_path / "permissions.yaml"
    store = PermissionsStore()
    store.set(SERVER, PID, "write_file", True)
    save_permissions(store, path)
    loaded = load_permissions(path)
    assert loaded.lookup(SERVER, PID, "write_file") is True


def test_load_corrupt_yaml_returns_empty(tmp_path):
    path = tmp_path / "permissions.yaml"
    path.write_text("{{{{invalid yaml")
    store = load_permissions(path)
    assert store.permissions == {}
```

- [ ] **Step 2: Run — verify they fail**

```bash
uv run pytest cli/tests/test_config_permissions.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement `config/permissions.py`**

```python
"""PermissionsStore — per server+project+tool approval decisions."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from balu_code_cli.config.paths import permissions_yaml


class PermissionsStore(BaseModel):
    permissions: dict[str, dict[str, dict[str, bool]]] = {}

    def lookup(self, server_url: str, project_id: int, tool_name: str) -> bool | None:
        return (
            self.permissions
            .get(server_url, {})
            .get(str(project_id), {})
            .get(tool_name)
        )

    def set(self, server_url: str, project_id: int, tool_name: str, approved: bool) -> None:
        (
            self.permissions
            .setdefault(server_url, {})
            .setdefault(str(project_id), {})
        )[tool_name] = approved


def load_permissions(path: Path | None = None) -> PermissionsStore:
    p = path or permissions_yaml()
    if not p.exists():
        return PermissionsStore()
    try:
        data = yaml.safe_load(p.read_text()) or {}
        return PermissionsStore.model_validate(data)
    except Exception:
        return PermissionsStore()


def save_permissions(store: PermissionsStore, path: Path | None = None) -> None:
    p = path or permissions_yaml()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(store.model_dump()))


__all__ = ["PermissionsStore", "load_permissions", "save_permissions"]
```

- [ ] **Step 4: Run — verify all pass**

```bash
uv run pytest cli/tests/test_config_permissions.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add cli/src/balu_code_cli/config/permissions.py cli/tests/test_config_permissions.py
git commit -m "feat(cli): add config/permissions.py (PermissionsStore)"
```

---

## Task 5: `config/balucode_yaml.py` — `.balucode.yaml` parser

**Files:**
- Create: `cli/src/balu_code_cli/config/balucode_yaml.py`
- Create: `cli/tests/test_config_balucode_yaml.py`

- [ ] **Step 1: Write failing tests**

`cli/tests/test_config_balucode_yaml.py`:
```python
"""Tests for config/balucode_yaml.py."""
from __future__ import annotations

import pytest

from balu_code_cli.config.balucode_yaml import (
    BaluCodeYaml,
    find_balucode_yaml,
    load_balucode_yaml,
)


def _write_yaml(path, content):
    path.write_text(content)


def test_load_minimal_yaml(tmp_path):
    f = tmp_path / ".balucode.yaml"
    f.write_text("project_id: 42\nserver_url: https://balu.example.com\n")
    cfg = load_balucode_yaml(f)
    assert cfg.project_id == 42
    assert cfg.server_url == "https://balu.example.com"
    assert cfg.model is None
    assert cfg.tools.allow_write is False
    assert cfg.tools.allow_bash is False
    assert cfg.tools.allow_web_fetch is True


def test_load_full_yaml(tmp_path):
    f = tmp_path / ".balucode.yaml"
    f.write_text(
        "project_id: 7\nserver_url: https://x.com\nmodel: llama3.1:8b\n"
        "tools:\n  allow_write: true\n  allow_bash: true\n  allow_web_fetch: false\n"
    )
    cfg = load_balucode_yaml(f)
    assert cfg.model == "llama3.1:8b"
    assert cfg.tools.allow_write is True
    assert cfg.tools.allow_bash is True
    assert cfg.tools.allow_web_fetch is False


def test_is_tool_allowed_write_file_when_allow_write_false():
    cfg = BaluCodeYaml(project_id=1, server_url="https://x.com")
    assert cfg.is_tool_allowed("write_file") is False
    assert cfg.is_tool_allowed("apply_patch") is False


def test_is_tool_allowed_write_file_when_allow_write_true():
    from balu_code_cli.config.balucode_yaml import ToolsConfig
    cfg = BaluCodeYaml(project_id=1, server_url="https://x.com",
                       tools=ToolsConfig(allow_write=True))
    assert cfg.is_tool_allowed("write_file") is True
    assert cfg.is_tool_allowed("apply_patch") is True


def test_is_tool_allowed_run_bash_default_false():
    cfg = BaluCodeYaml(project_id=1, server_url="https://x.com")
    assert cfg.is_tool_allowed("run_bash") is False


def test_is_tool_allowed_web_fetch_default_true():
    cfg = BaluCodeYaml(project_id=1, server_url="https://x.com")
    assert cfg.is_tool_allowed("web_fetch") is True


def test_is_tool_allowed_read_file_always_true():
    cfg = BaluCodeYaml(project_id=1, server_url="https://x.com")
    assert cfg.is_tool_allowed("read_file") is True
    assert cfg.is_tool_allowed("glob") is True


def test_find_balucode_yaml_finds_in_cwd(tmp_path):
    f = tmp_path / ".balucode.yaml"
    f.write_text("project_id: 1\nserver_url: https://x.com\n")
    found = find_balucode_yaml(tmp_path)
    assert found == f


def test_find_balucode_yaml_walks_up(tmp_path):
    f = tmp_path / ".balucode.yaml"
    f.write_text("project_id: 1\nserver_url: https://x.com\n")
    subdir = tmp_path / "a" / "b" / "c"
    subdir.mkdir(parents=True)
    found = find_balucode_yaml(subdir)
    assert found == f


def test_find_balucode_yaml_returns_none_when_not_found(tmp_path):
    assert find_balucode_yaml(tmp_path) is None


def test_load_balucode_yaml_raises_when_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="balu-code init"):
        load_balucode_yaml()  # no file in cwd during tests (tmp_path not used here)
```

- [ ] **Step 2: Run — verify they fail**

```bash
uv run pytest cli/tests/test_config_balucode_yaml.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement `config/balucode_yaml.py`**

```python
"""BaluCodeYaml — .balucode.yaml parser + walk-up search."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class ToolsConfig(BaseModel):
    allow_write: bool = False
    allow_bash: bool = False
    allow_web_fetch: bool = True


_WRITE_TOOLS = {"write_file", "apply_patch"}
_BASH_TOOLS = {"run_bash"}
_NETWORK_TOOLS = {"web_fetch"}


class BaluCodeYaml(BaseModel):
    project_id: int
    server_url: str
    model: str | None = None
    tools: ToolsConfig = ToolsConfig()

    def is_tool_allowed(self, tool_name: str) -> bool:
        if tool_name in _WRITE_TOOLS:
            return self.tools.allow_write
        if tool_name in _BASH_TOOLS:
            return self.tools.allow_bash
        if tool_name in _NETWORK_TOOLS:
            return self.tools.allow_web_fetch
        return True


def find_balucode_yaml(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    while True:
        candidate = current / ".balucode.yaml"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def load_balucode_yaml(path: Path | None = None) -> BaluCodeYaml:
    found = path or find_balucode_yaml()
    if found is None:
        raise FileNotFoundError(
            "No .balucode.yaml found. Run `balu-code init` first."
        )
    return BaluCodeYaml.model_validate(yaml.safe_load(found.read_text()))


__all__ = ["BaluCodeYaml", "ToolsConfig", "find_balucode_yaml", "load_balucode_yaml"]
```

- [ ] **Step 4: Run — verify all pass**

```bash
uv run pytest cli/tests/test_config_balucode_yaml.py -v
```

Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
git add cli/src/balu_code_cli/config/balucode_yaml.py cli/tests/test_config_balucode_yaml.py
git commit -m "feat(cli): add config/balucode_yaml.py (.balucode.yaml parser)"
```

---

## Task 6: `client/http.py` — REST client

**Files:**
- Create: `cli/src/balu_code_cli/client/http.py`
- Create: `cli/tests/test_client_http.py`

- [ ] **Step 1: Write failing tests**

`cli/tests/test_client_http.py`:
```python
"""Tests for client/http.py — uses respx to mock httpx."""
from __future__ import annotations

import httpx
import pytest
import respx

from balu_code_cli.client.http import BaluCodeHttpClient

BASE = "https://balu.example.com/api/plugins/balu_code"


@respx.mock
def test_health_returns_dict():
    respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"status": "ok", "plugin": "balu_code", "version": "0.1.0"})
    )
    client = BaluCodeHttpClient("https://balu.example.com", "bc_test")
    result = client.health()
    assert result["status"] == "ok"


@respx.mock
def test_health_sends_bearer_token():
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    BaluCodeHttpClient("https://balu.example.com", "bc_secret").health()
    assert route.calls[0].request.headers["authorization"] == "Bearer bc_secret"


@respx.mock
def test_list_models_returns_names():
    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(200, json={
            "models": [
                {"name": "llama3.1:8b", "size": 1000, "digest": "abc"},
                {"name": "codellama:7b", "size": 2000, "digest": "def"},
            ]
        })
    )
    client = BaluCodeHttpClient("https://balu.example.com", "key")
    assert client.list_models() == ["llama3.1:8b", "codellama:7b"]


@respx.mock
def test_create_project_posts_correct_body():
    route = respx.post(f"{BASE}/projects").mock(
        return_value=httpx.Response(201, json={"id": 5, "name": "myproj", "root_path": "/home/x/proj"})
    )
    client = BaluCodeHttpClient("https://balu.example.com", "key")
    result = client.create_project("myproj", "/home/x/proj")
    assert result["id"] == 5
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["name"] == "myproj"
    assert body["root_path"] == "/home/x/proj"


@respx.mock
def test_start_index_returns_job():
    respx.post(f"{BASE}/projects/3/index").mock(
        return_value=httpx.Response(202, json={"job_id": "j1", "project_id": 3, "status": "running"})
    )
    client = BaluCodeHttpClient("https://balu.example.com", "key")
    result = client.start_index(3)
    assert result["job_id"] == "j1"


@respx.mock
def test_index_status_returns_status():
    respx.get(f"{BASE}/projects/3/index/status/j1").mock(
        return_value=httpx.Response(200, json={
            "job_id": "j1", "project_id": 3, "status": "done",
            "files_total": 10, "files_processed": 10, "chunks_total": 80,
            "error": None, "started_at": None, "finished_at": None,
        })
    )
    client = BaluCodeHttpClient("https://balu.example.com", "key")
    result = client.index_status(3, "j1")
    assert result["status"] == "done"
    assert result["files_total"] == 10


@respx.mock
def test_http_error_raises():
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(401))
    client = BaluCodeHttpClient("https://balu.example.com", "bad_key")
    with pytest.raises(httpx.HTTPStatusError):
        client.health()
```

- [ ] **Step 2: Run — verify they fail**

```bash
uv run pytest cli/tests/test_client_http.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement `client/http.py`**

```python
"""BaluCodeHttpClient — httpx-based REST wrapper."""

from __future__ import annotations

import httpx


class BaluCodeHttpClient:
    def __init__(self, server_url: str, api_key: str) -> None:
        self._base = server_url.rstrip("/") + "/api/plugins/balu_code"
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def _get(self, path: str) -> dict:
        with httpx.Client(headers=self._headers, timeout=10) as client:
            r = client.get(self._base + path)
            r.raise_for_status()
            return r.json()

    def _post(self, path: str, json: dict | None = None) -> dict:
        with httpx.Client(headers=self._headers, timeout=10) as client:
            r = client.post(self._base + path, json=json or {})
            r.raise_for_status()
            return r.json()

    def health(self) -> dict:
        return self._get("/health")

    def list_models(self) -> list[str]:
        data = self._get("/models")
        return [m["name"] for m in data.get("models", [])]

    def create_project(self, name: str, root_path: str) -> dict:
        return self._post("/projects", {"name": name, "root_path": root_path})

    def start_index(self, project_id: int) -> dict:
        return self._post(f"/projects/{project_id}/index")

    def index_status(self, project_id: int, job_id: str) -> dict:
        return self._get(f"/projects/{project_id}/index/status/{job_id}")


__all__ = ["BaluCodeHttpClient"]
```

- [ ] **Step 4: Run — verify all pass**

```bash
uv run pytest cli/tests/test_client_http.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add cli/src/balu_code_cli/client/http.py cli/tests/test_client_http.py
git commit -m "feat(cli): add client/http.py (BaluCodeHttpClient)"
```

---

## Task 7: `client/ws.py` — WebSocket client

**Files:**
- Create: `cli/src/balu_code_cli/client/ws.py`
- Create: `cli/tests/test_client_ws.py`

- [ ] **Step 1: Write failing tests**

`cli/tests/test_client_ws.py`:
```python
"""Tests for client/ws.py — real local websockets server."""
from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from balu_code_cli.client.ws import BaluCodeWS, connect


async def _make_server(handler):
    server = await websockets.serve(handler, "localhost", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


@pytest.mark.asyncio
async def test_send_message_sends_user_message_frame():
    received = []

    async def handler(ws):
        raw = await ws.recv()
        received.append(json.loads(raw))
        # send turn_end so client doesn't hang
        await ws.send(json.dumps({
            "type": "turn_end", "turn_id": "t_1",
            "total_tokens": 0, "iterations": 0, "stop_reason": "done"
        }))

    server, port = await _make_server(handler)
    try:
        async with connect(f"http://localhost:{port}", "test_key", 1) as ws:
            await ws.send_message("hello world")
    finally:
        server.close()
        await server.wait_closed()

    assert received[0]["type"] == "user_message"
    assert received[0]["content"] == "hello world"


@pytest.mark.asyncio
async def test_receive_parses_token_event():
    async def handler(ws):
        await ws.recv()  # consume user_message
        await ws.send(json.dumps({"type": "token", "content": "Hi"}))
        await ws.send(json.dumps({
            "type": "turn_end", "turn_id": "t_1",
            "total_tokens": 1, "iterations": 1, "stop_reason": "done"
        }))

    server, port = await _make_server(handler)
    try:
        async with connect(f"http://localhost:{port}", "key", 1) as ws:
            await ws.send_message("hi")
            ev = await ws.receive()
            assert ev.type == "token"
            assert ev.content == "Hi"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_send_approval_sends_approval_frame():
    received = []

    async def handler(ws):
        await ws.recv()  # user_message
        # send approval_request
        await ws.send(json.dumps({
            "type": "approval_request", "tool_call_id": "tc_1",
            "tool": "write_file", "args": {}, "risk": "write"
        }))
        raw = await ws.recv()
        received.append(json.loads(raw))
        await ws.send(json.dumps({
            "type": "turn_end", "turn_id": "t_1",
            "total_tokens": 0, "iterations": 1, "stop_reason": "done"
        }))

    server, port = await _make_server(handler)
    try:
        async with connect(f"http://localhost:{port}", "key", 1) as ws:
            await ws.send_message("go")
            _ = await ws.receive()  # approval_request
            await ws.send_approval("tc_1", approved=True)
    finally:
        server.close()
        await server.wait_closed()

    assert received[0]["type"] == "approval"
    assert received[0]["tool_call_id"] == "tc_1"
    assert received[0]["approved"] is True


@pytest.mark.asyncio
async def test_send_cancel_sends_cancel_frame():
    received = []

    async def handler(ws):
        await ws.recv()  # user_message
        raw = await ws.recv()
        received.append(json.loads(raw))

    server, port = await _make_server(handler)
    try:
        async with connect(f"http://localhost:{port}", "key", 1) as ws:
            await ws.send_message("go")
            await ws.send_cancel("t_abc")
    finally:
        server.close()
        await server.wait_closed()

    assert received[0]["type"] == "cancel"
    assert received[0]["turn_id"] == "t_abc"
```

- [ ] **Step 2: Run — verify they fail**

```bash
uv run pytest cli/tests/test_client_ws.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement `client/ws.py`**

```python
"""BaluCodeWS — asyncio WebSocket client."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

import websockets
from balu_code_shared.events import Event, parse_frame


def _ws_url(server_url: str, project_id: int) -> str:
    url = server_url.rstrip("/")
    url = url.replace("https://", "wss://").replace("http://", "ws://")
    return f"{url}/api/plugins/balu_code/chat?project_id={project_id}"


class BaluCodeWS:
    def __init__(self, ws) -> None:
        self._ws = ws

    async def send_message(self, content: str) -> None:
        await self._ws.send(json.dumps({"type": "user_message", "content": content}))

    async def send_approval(
        self, tool_call_id: str, approved: bool, reason: str | None = None
    ) -> None:
        payload: dict = {"type": "approval", "tool_call_id": tool_call_id, "approved": approved}
        if reason:
            payload["reason"] = reason
        await self._ws.send(json.dumps(payload))

    async def send_cancel(self, turn_id: str) -> None:
        await self._ws.send(json.dumps({"type": "cancel", "turn_id": turn_id}))

    async def receive(self) -> Event:
        raw = await self._ws.recv()
        return parse_frame(json.loads(raw))


@asynccontextmanager
async def connect(
    server_url: str, api_key: str, project_id: int
) -> AsyncIterator[BaluCodeWS]:
    url = _ws_url(server_url, project_id)
    extra = {"Authorization": f"Bearer {api_key}"}
    async with websockets.connect(url, additional_headers=extra) as ws:
        yield BaluCodeWS(ws)


__all__ = ["BaluCodeWS", "connect"]
```

- [ ] **Step 4: Run — verify all pass**

```bash
uv run pytest cli/tests/test_client_ws.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add cli/src/balu_code_cli/client/ws.py cli/tests/test_client_ws.py
git commit -m "feat(cli): add client/ws.py (BaluCodeWS asyncio client)"
```

---

## Task 8: `commands/auth.py` — auth login + status

**Files:**
- Create: `cli/src/balu_code_cli/commands/auth.py`
- Create: `cli/tests/test_cmd_auth.py`

- [ ] **Step 1: Write failing tests**

`cli/tests/test_cmd_auth.py`:
```python
"""Tests for commands/auth.py."""
from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from balu_code_cli.__main__ import app

runner = CliRunner()
BASE = "https://balu.example.com/api/plugins/balu_code"


@respx.mock
def test_auth_login_success(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import importlib, balu_code_cli.config.paths as p
    importlib.reload(p)

    respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    result = runner.invoke(
        app,
        ["auth", "login"],
        input="https://balu.example.com\nbc_testkey123\n",
    )
    assert result.exit_code == 0
    assert "Logged in" in result.output


@respx.mock
def test_auth_login_bad_key_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import importlib, balu_code_cli.config.paths as p
    importlib.reload(p)

    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(401))
    result = runner.invoke(
        app,
        ["auth", "login"],
        input="https://balu.example.com\nbad_key\n",
    )
    assert result.exit_code != 0


@respx.mock
def test_auth_status_shows_server(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import importlib, balu_code_cli.config.paths as p
    importlib.reload(p)

    # Pre-populate credentials
    from balu_code_cli.config.loader import Credentials, ServerCredentials, save_credentials, save_config, AppConfig
    importlib.reload(p)
    save_config(AppConfig(server_url="https://balu.example.com"), p.config_yaml())
    save_credentials(
        Credentials(servers={"https://balu.example.com": ServerCredentials(api_key="bc_abc12345")}),
        p.credentials_yaml(),
    )

    respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
    assert "balu.example.com" in result.output
```

- [ ] **Step 2: Run — verify they fail**

```bash
uv run pytest cli/tests/test_cmd_auth.py -v
```

Expected: command not found or import errors.

- [ ] **Step 3: Implement `commands/auth.py`**

```python
"""auth login + auth status commands."""

from __future__ import annotations

import sys

import httpx
import typer
from rich.console import Console
from rich.table import Table

from balu_code_cli.client.http import BaluCodeHttpClient
from balu_code_cli.config.loader import (
    AppConfig,
    Credentials,
    ServerCredentials,
    load_config,
    load_credentials,
    save_config,
    save_credentials,
)

app = typer.Typer(help="Manage authentication.")
console = Console()


@app.command("login")
def login() -> None:
    """Authenticate with a BaluHost server using an API key."""
    cfg = load_config()
    server_url = typer.prompt("Server URL", default=cfg.server_url or "")
    api_key = typer.prompt("API key", hide_input=True)

    try:
        BaluCodeHttpClient(server_url, api_key).health()
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]Authentication failed (HTTP {exc.response.status_code}). Check your API key.[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]Could not reach server: {exc}[/red]")
        raise typer.Exit(1)

    creds = load_credentials()
    creds.servers[server_url] = ServerCredentials(api_key=api_key)
    save_credentials(creds)

    cfg.server_url = server_url
    save_config(cfg)

    console.print(f"[green]Logged in to {server_url}[/green]")


@app.command("status")
def status() -> None:
    """Show current authentication status."""
    cfg = load_config()
    creds = load_credentials()

    if not cfg.server_url or cfg.server_url not in creds.servers:
        console.print("[yellow]Not logged in. Run `balu-code auth login`.[/yellow]")
        raise typer.Exit(1)

    server_url = cfg.server_url
    api_key = creds.servers[server_url].api_key

    try:
        BaluCodeHttpClient(server_url, api_key).health()
        ok = "✓ ok"
    except Exception:
        ok = "✗ unreachable"

    table = Table(title="Auth Status")
    table.add_column("Server")
    table.add_column("API Key")
    table.add_column("Status")
    table.add_row(server_url, api_key[:8] + "...", ok)
    console.print(table)
```

- [ ] **Step 4: Register auth group in `__main__.py`**

Replace `cli/src/balu_code_cli/__main__.py` with:
```python
"""Typer entry point for `balu-code`."""

from __future__ import annotations

import typer

from balu_code_cli import __version__
from balu_code_cli.commands.auth import app as auth_app

app = typer.Typer(
    name="balu-code",
    no_args_is_help=True,
    add_completion=False,
    help="Balu Code — self-hosted coding agent.",
)
app.add_typer(auth_app, name="auth")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"balu-code {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Balu Code terminal client."""
```

- [ ] **Step 5: Run — verify all pass**

```bash
uv run pytest cli/tests/test_cmd_auth.py cli/tests/test_version.py -v
```

Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
git add cli/src/balu_code_cli/commands/auth.py \
        cli/src/balu_code_cli/__main__.py \
        cli/tests/test_cmd_auth.py
git commit -m "feat(cli): add auth login + auth status commands"
```

---

## Task 9: `commands/init.py` — project init wizard

**Files:**
- Create: `cli/src/balu_code_cli/commands/init.py`
- Create: `cli/tests/test_cmd_init.py`

- [ ] **Step 1: Write failing tests**

`cli/tests/test_cmd_init.py`:
```python
"""Tests for commands/init.py."""
from __future__ import annotations

import httpx
import respx
import yaml
from typer.testing import CliRunner

from balu_code_cli.__main__ import app

runner = CliRunner()
BASE = "https://balu.example.com/api/plugins/balu_code"


def _setup_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import importlib, balu_code_cli.config.paths as p
    importlib.reload(p)
    from balu_code_cli.config.loader import AppConfig, Credentials, ServerCredentials, save_config, save_credentials
    save_config(AppConfig(server_url="https://balu.example.com"), p.config_yaml())
    save_credentials(
        Credentials(servers={"https://balu.example.com": ServerCredentials(api_key="bc_key")}),
        p.credentials_yaml(),
    )


@respx.mock
def test_init_creates_balucode_yaml(tmp_path, monkeypatch):
    _setup_auth(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)

    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "llama3.1:8b", "size": 1, "digest": "a"}]})
    )
    respx.post(f"{BASE}/projects").mock(
        return_value=httpx.Response(201, json={"id": 7, "name": "myproj", "root_path": str(tmp_path)})
    )

    result = runner.invoke(
        app, ["init"],
        input=f"myproj\n{tmp_path}\nllama3.1:8b\n",
    )
    assert result.exit_code == 0, result.output
    balucode = tmp_path / ".balucode.yaml"
    assert balucode.exists()
    data = yaml.safe_load(balucode.read_text())
    assert data["project_id"] == 7
    assert data["server_url"] == "https://balu.example.com"
    assert data["model"] == "llama3.1:8b"


@respx.mock
def test_init_aborts_if_balucode_yaml_exists_and_user_declines(tmp_path, monkeypatch):
    _setup_auth(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".balucode.yaml").write_text("project_id: 1\nserver_url: x\n")

    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "llama3.1:8b", "size": 1, "digest": "a"}]})
    )

    result = runner.invoke(app, ["init"], input="n\n")
    assert result.exit_code == 0
    # File not overwritten
    assert yaml.safe_load((tmp_path / ".balucode.yaml").read_text())["project_id"] == 1
```

- [ ] **Step 2: Run — verify they fail**

```bash
uv run pytest cli/tests/test_cmd_init.py -v
```

Expected: command not found.

- [ ] **Step 3: Implement `commands/init.py`**

```python
"""init wizard — creates .balucode.yaml in cwd."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console

from balu_code_cli.client.http import BaluCodeHttpClient
from balu_code_cli.config.loader import load_config, load_credentials

app = typer.Typer(help="Initialise a project in the current directory.")
console = Console()


@app.callback(invoke_without_command=True)
def init() -> None:
    """Interactively create a .balucode.yaml for this directory."""
    cfg = load_config()
    creds = load_credentials()

    server_url = cfg.server_url
    if not server_url or server_url not in creds.servers:
        console.print("[red]Not logged in. Run `balu-code auth login` first.[/red]")
        raise typer.Exit(1)

    api_key = creds.servers[server_url].api_key
    client = BaluCodeHttpClient(server_url, api_key)

    balucode_path = Path.cwd() / ".balucode.yaml"
    if balucode_path.exists():
        overwrite = typer.confirm(".balucode.yaml already exists. Overwrite?", default=False)
        if not overwrite:
            raise typer.Exit(0)

    # Fetch models for selection
    try:
        models = client.list_models()
    except Exception as exc:
        console.print(f"[red]Could not fetch models: {exc}[/red]")
        raise typer.Exit(1)

    name = typer.prompt("Project name")
    root_path = typer.prompt("Root path", default=str(Path.cwd()))

    if models:
        console.print("Available models: " + ", ".join(models))
    model = typer.prompt("Model", default=models[0] if models else "")

    try:
        project = client.create_project(name, root_path)
    except Exception as exc:
        console.print(f"[red]Failed to create project: {exc}[/red]")
        raise typer.Exit(1)

    project_id = project["id"]
    data = {
        "project_id": project_id,
        "server_url": server_url,
        "model": model or None,
        "tools": {
            "allow_write": False,
            "allow_bash": False,
            "allow_web_fetch": True,
        },
    }
    balucode_path.write_text(yaml.dump(data))
    console.print(f"[green]Project #{project_id} initialised.[/green] Run `balu-code index` to build the RAG index.")
```

- [ ] **Step 4: Register in `__main__.py`**

Add to `__main__.py` (after `from balu_code_cli.commands.auth import app as auth_app`):
```python
from balu_code_cli.commands.init import app as init_app

# after app.add_typer(auth_app, name="auth"):
app.add_typer(init_app, name="init")
```

- [ ] **Step 5: Run — verify all pass**

```bash
uv run pytest cli/tests/test_cmd_init.py -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add cli/src/balu_code_cli/commands/init.py \
        cli/src/balu_code_cli/__main__.py \
        cli/tests/test_cmd_init.py
git commit -m "feat(cli): add init wizard command"
```

---

## Task 10: `commands/models.py` + `commands/index.py`

**Files:**
- Create: `cli/src/balu_code_cli/commands/models.py`
- Create: `cli/src/balu_code_cli/commands/index.py`
- Create: `cli/tests/test_cmd_models.py`
- Create: `cli/tests/test_cmd_index.py`

- [ ] **Step 1: Write failing tests**

`cli/tests/test_cmd_models.py`:
```python
"""Tests for commands/models.py."""
from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from balu_code_cli.__main__ import app

runner = CliRunner()
BASE = "https://balu.example.com/api/plugins/balu_code"


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import importlib, balu_code_cli.config.paths as p
    importlib.reload(p)
    from balu_code_cli.config.loader import AppConfig, Credentials, ServerCredentials, save_config, save_credentials
    save_config(AppConfig(server_url="https://balu.example.com"), p.config_yaml())
    save_credentials(
        Credentials(servers={"https://balu.example.com": ServerCredentials(api_key="bc_key")}),
        p.credentials_yaml(),
    )


@respx.mock
def test_models_lists_names(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(200, json={
            "models": [
                {"name": "llama3.1:8b", "size": 4_000_000_000, "digest": "abc"},
                {"name": "codellama:7b", "size": 3_500_000_000, "digest": "def"},
            ]
        })
    )
    result = runner.invoke(app, ["models"])
    assert result.exit_code == 0
    assert "llama3.1:8b" in result.output
    assert "codellama:7b" in result.output
```

`cli/tests/test_cmd_index.py`:
```python
"""Tests for commands/index.py."""
from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from balu_code_cli.__main__ import app

runner = CliRunner()
BASE = "https://balu.example.com/api/plugins/balu_code"


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import importlib, balu_code_cli.config.paths as p
    importlib.reload(p)
    from balu_code_cli.config.loader import AppConfig, Credentials, ServerCredentials, save_config, save_credentials
    save_config(AppConfig(server_url="https://balu.example.com"), p.config_yaml())
    save_credentials(
        Credentials(servers={"https://balu.example.com": ServerCredentials(api_key="bc_key")}),
        p.credentials_yaml(),
    )


@respx.mock
def test_index_polls_until_done(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / ".balucode.yaml").write_text(
        "project_id: 3\nserver_url: https://balu.example.com\n"
    )
    monkeypatch.chdir(tmp_path)

    respx.post(f"{BASE}/projects/3/index").mock(
        return_value=httpx.Response(202, json={"job_id": "j1", "project_id": 3, "status": "running"})
    )
    respx.get(f"{BASE}/projects/3/index/status/j1").mock(
        return_value=httpx.Response(200, json={
            "job_id": "j1", "project_id": 3, "status": "done",
            "files_total": 20, "files_processed": 20, "chunks_total": 150,
            "error": None, "started_at": None, "finished_at": None,
        })
    )
    result = runner.invoke(app, ["index"])
    assert result.exit_code == 0
    assert "20" in result.output  # files_total


@respx.mock
def test_index_shows_error_on_failure(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / ".balucode.yaml").write_text(
        "project_id: 3\nserver_url: https://balu.example.com\n"
    )
    monkeypatch.chdir(tmp_path)

    respx.post(f"{BASE}/projects/3/index").mock(
        return_value=httpx.Response(202, json={"job_id": "j2", "project_id": 3, "status": "running"})
    )
    respx.get(f"{BASE}/projects/3/index/status/j2").mock(
        return_value=httpx.Response(200, json={
            "job_id": "j2", "project_id": 3, "status": "failed",
            "files_total": 0, "files_processed": 0, "chunks_total": 0,
            "error": "disk full", "started_at": None, "finished_at": None,
        })
    )
    result = runner.invoke(app, ["index"])
    assert result.exit_code != 0
    assert "disk full" in result.output
```

- [ ] **Step 2: Run — verify they fail**

```bash
uv run pytest cli/tests/test_cmd_models.py cli/tests/test_cmd_index.py -v
```

Expected: command not found.

- [ ] **Step 3: Implement `commands/models.py`**

```python
"""models — list available Ollama models."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from balu_code_cli.client.http import BaluCodeHttpClient
from balu_code_cli.config.loader import load_config, load_credentials

app = typer.Typer(help="List available models.")
console = Console()


@app.callback(invoke_without_command=True)
def models() -> None:
    """List models available on the configured server."""
    cfg = load_config()
    creds = load_credentials()
    if not cfg.server_url or cfg.server_url not in creds.servers:
        console.print("[red]Not logged in. Run `balu-code auth login` first.[/red]")
        raise typer.Exit(1)

    client = BaluCodeHttpClient(cfg.server_url, creds.servers[cfg.server_url].api_key)
    try:
        names = client.list_models()
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    table = Table(title="Available Models")
    table.add_column("Name")
    for name in names:
        table.add_row(name)
    console.print(table)
```

- [ ] **Step 4: Implement `commands/index.py`**

```python
"""index — start indexing and poll until done."""

from __future__ import annotations

import time

import typer
from rich.console import Console

from balu_code_cli.client.http import BaluCodeHttpClient
from balu_code_cli.config.balucode_yaml import load_balucode_yaml
from balu_code_cli.config.loader import load_credentials

app = typer.Typer(help="Index the current project.")
console = Console()
_POLL_INTERVAL = 2  # seconds


@app.callback(invoke_without_command=True)
def index() -> None:
    """Start indexing the current project and wait for completion."""
    try:
        balucode = load_balucode_yaml()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    creds = load_credentials()
    if balucode.server_url not in creds.servers:
        console.print("[red]Not logged in. Run `balu-code auth login` first.[/red]")
        raise typer.Exit(1)

    client = BaluCodeHttpClient(balucode.server_url, creds.servers[balucode.server_url].api_key)

    try:
        job = client.start_index(balucode.project_id)
    except Exception as exc:
        console.print(f"[red]Failed to start index: {exc}[/red]")
        raise typer.Exit(1)

    job_id = job["job_id"]
    with console.status("[bold green]Indexing…"):
        while True:
            try:
                status = client.index_status(balucode.project_id, job_id)
            except Exception as exc:
                console.print(f"[red]Error polling status: {exc}[/red]")
                raise typer.Exit(1)

            if status["status"] == "done":
                console.print(
                    f"[green]Done.[/green] "
                    f"{status['files_processed']}/{status['files_total']} files, "
                    f"{status['chunks_total']} chunks."
                )
                return
            if status["status"] == "failed":
                console.print(f"[red]Indexing failed: {status.get('error')}[/red]")
                raise typer.Exit(1)

            time.sleep(_POLL_INTERVAL)
```

- [ ] **Step 5: Register in `__main__.py`**

Add after existing imports and `add_typer` calls:
```python
from balu_code_cli.commands.models import app as models_app
from balu_code_cli.commands.index import app as index_app

app.add_typer(models_app, name="models")
app.add_typer(index_app, name="index")
```

- [ ] **Step 6: Run — verify all pass**

```bash
uv run pytest cli/tests/test_cmd_models.py cli/tests/test_cmd_index.py -v
```

Expected: `3 passed`

- [ ] **Step 7: Commit**

```bash
git add cli/src/balu_code_cli/commands/models.py \
        cli/src/balu_code_cli/commands/index.py \
        cli/src/balu_code_cli/__main__.py \
        cli/tests/test_cmd_models.py \
        cli/tests/test_cmd_index.py
git commit -m "feat(cli): add models + index commands"
```

---

## Task 11: `commands/chat.py` — REPL core + streaming display

**Files:**
- Create: `cli/src/balu_code_cli/commands/chat.py`
- Create: `cli/tests/test_cmd_chat.py`

- [ ] **Step 1: Write failing tests (streaming display)**

`cli/tests/test_cmd_chat.py`:
```python
"""Tests for commands/chat.py."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from balu_code_cli.__main__ import app
from balu_code_cli.client.ws import BaluCodeWS
from balu_code_cli.commands.chat import run_chat
from balu_code_cli.config.balucode_yaml import BaluCodeYaml

runner = CliRunner()
_BALUCODE = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")


def _make_fake_ws(events: list[dict]) -> BaluCodeWS:
    """Return a BaluCodeWS that replays the given frames."""
    from balu_code_shared.events import parse_frame
    ws = MagicMock(spec=BaluCodeWS)
    frames = [parse_frame(e) for e in events]
    call_count = [0]

    async def recv():
        ev = frames[call_count[0]]
        call_count[0] += 1
        return ev

    ws.receive = recv
    ws.send_message = AsyncMock()
    ws.send_approval = AsyncMock()
    ws.send_cancel = AsyncMock()
    return ws


def _make_ws_factory(ws):
    @asynccontextmanager
    async def factory(server_url, api_key, project_id) -> AsyncIterator[BaluCodeWS]:
        yield ws
    return factory


@pytest.mark.asyncio
async def test_run_chat_streams_tokens(capsys):
    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 10},
        {"type": "token", "content": "Hello"},
        {"type": "token", "content": " world"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 15, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)

    # Simulate one user message then EOF
    inputs = asyncio.Queue()
    await inputs.put("write a function")
    await inputs.put(EOFError())

    async def fake_input(_prompt=""):
        item = await inputs.get()
        if isinstance(item, BaseException):
            raise item
        return item

    await run_chat(
        balucode=_BALUCODE,
        api_key="key",
        yolo=False,
        project_id=1,
        ws_factory=_make_ws_factory(ws),
        input_fn=fake_input,
    )

    captured = capsys.readouterr()
    assert "Hello" in captured.out
    assert " world" in captured.out


@pytest.mark.asyncio
async def test_run_chat_displays_tool_call(capsys):
    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "tool_call", "tool_call_id": "tc_1", "tool": "read_file",
         "args": {"path": "foo.py"}, "auto_approved": True},
        {"type": "tool_result", "tool_call_id": "tc_1", "status": "ok", "bytes_out": 42, "error": None},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 10, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    inputs = asyncio.Queue()
    await inputs.put("read foo")
    await inputs.put(EOFError())

    async def fake_input(_prompt=""):
        item = await inputs.get()
        if isinstance(item, BaseException):
            raise item
        return item

    await run_chat(
        balucode=_BALUCODE,
        api_key="key",
        yolo=False,
        project_id=1,
        ws_factory=_make_ws_factory(ws),
        input_fn=fake_input,
    )
    captured = capsys.readouterr()
    assert "read_file" in captured.out
```

- [ ] **Step 2: Run — verify they fail**

```bash
uv run pytest cli/tests/test_cmd_chat.py::test_run_chat_streams_tokens \
             cli/tests/test_cmd_chat.py::test_run_chat_displays_tool_call -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement `commands/chat.py` (core, no approval yet)**

```python
"""chat — interactive REPL with streaming output."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Awaitable
from contextlib import asynccontextmanager
from typing import Any

import typer
from rich.console import Console

from balu_code_cli.client.ws import BaluCodeWS, connect
from balu_code_cli.config.balucode_yaml import BaluCodeYaml, load_balucode_yaml
from balu_code_cli.config.loader import load_credentials
from balu_code_cli.config.permissions import load_permissions, save_permissions
from balu_code_cli.config.paths import permissions_yaml

app = typer.Typer(help="Start an interactive chat session.")
console = Console()

InputFn = Callable[[str], Awaitable[str]]


async def _default_input(prompt: str = "") -> str:
    return await asyncio.to_thread(input, prompt)


def _format_args(args: dict) -> str:
    parts = [f'{k}={repr(v)[:40]}' for k, v in list(args.items())[:3]]
    return ", ".join(parts)


async def _dispatch_turn(ws: BaluCodeWS, balucode: BaluCodeYaml, yolo: bool) -> str | None:
    """Dispatch events for one turn. Returns turn_id when done."""
    turn_id = None
    first_token = True

    while True:
        event = await ws.receive()

        if event.type == "turn_start":
            turn_id = event.turn_id

        elif event.type == "token":
            if first_token:
                first_token = False
            print(event.content, end="", flush=True)

        elif event.type == "tool_call":
            label = "(auto)" if event.auto_approved else ""
            print(f"\n🔧 {event.tool}({_format_args(event.args)}) {label}", flush=True)

        elif event.type == "tool_result":
            if event.status == "ok":
                print(f"  ✓ ok ({event.bytes_out} bytes)", flush=True)
            else:
                print(f"  ✗ error: {event.error}", flush=True)

        elif event.type == "approval_request":
            await _handle_approval(ws, event, balucode, yolo)

        elif event.type == "turn_end":
            print()
            return turn_id

        elif event.type == "error":
            console.print(f"[red]Error [{event.code}]: {event.message}[/red]")

    return turn_id


async def _handle_approval(ws, event, balucode: BaluCodeYaml, yolo: bool) -> None:
    """Resolve an approval_request. Placeholder — full logic in Task 12."""
    # Phase 5a Task 11: always auto-approve (Task 12 adds real approval logic)
    await ws.send_approval(event.tool_call_id, approved=True)


async def run_chat(
    balucode: BaluCodeYaml,
    api_key: str,
    yolo: bool,
    project_id: int,
    ws_factory=None,
    input_fn: InputFn = _default_input,
) -> None:
    _connect = ws_factory or connect

    async with _connect(balucode.server_url, api_key, project_id) as ws:
        while True:
            try:
                line = await input_fn("[balu-code] > ")
            except (EOFError, KeyboardInterrupt):
                break

            line = line.strip()
            if not line:
                continue
            if line in (".exit", ".quit"):
                break

            await ws.send_message(line)
            turn_id = None
            try:
                turn_id = await _dispatch_turn(ws, balucode, yolo)
            except KeyboardInterrupt:
                if turn_id:
                    await ws.send_cancel(turn_id)
                    console.print("[yellow]Cancelled[/yellow]")


@app.callback(invoke_without_command=True)
def chat(
    yolo: bool = typer.Option(False, "--yolo", help="Auto-approve all tool calls."),
    project_id: int | None = typer.Option(None, "--project-id", help="Override project ID."),
) -> None:
    """Start an interactive chat REPL."""
    try:
        balucode = load_balucode_yaml()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    creds = load_credentials()
    if balucode.server_url not in creds.servers:
        console.print("[red]Not logged in. Run `balu-code auth login` first.[/red]")
        raise typer.Exit(1)

    api_key = creds.servers[balucode.server_url].api_key
    pid = project_id or balucode.project_id

    asyncio.run(run_chat(balucode=balucode, api_key=api_key, yolo=yolo, project_id=pid))
```

- [ ] **Step 4: Register in `__main__.py`**

Add:
```python
from balu_code_cli.commands.chat import app as chat_app
app.add_typer(chat_app, name="chat")
```

- [ ] **Step 5: Run — verify tests pass**

```bash
uv run pytest cli/tests/test_cmd_chat.py::test_run_chat_streams_tokens \
             cli/tests/test_cmd_chat.py::test_run_chat_displays_tool_call -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add cli/src/balu_code_cli/commands/chat.py \
        cli/src/balu_code_cli/__main__.py \
        cli/tests/test_cmd_chat.py
git commit -m "feat(cli): add chat REPL with streaming display"
```

---

## Task 12: Approval flow in `commands/chat.py`

**Files:**
- Modify: `cli/src/balu_code_cli/commands/chat.py` (replace `_handle_approval`)
- Modify: `cli/tests/test_cmd_chat.py` (add approval tests)

- [ ] **Step 1: Write failing tests**

Add to `cli/tests/test_cmd_chat.py`:
```python
@pytest.mark.asyncio
async def test_yolo_auto_approves_without_prompt(capsys):
    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "approval_request", "tool_call_id": "tc_1",
         "tool": "write_file", "args": {"path": "x.py"}, "risk": "write"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 5, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    inputs = asyncio.Queue()
    await inputs.put("go")
    await inputs.put(EOFError())

    async def fake_input(_p=""): return await inputs.get()

    await run_chat(
        balucode=_BALUCODE, api_key="key", yolo=True,
        project_id=1, ws_factory=_make_ws_factory(ws), input_fn=fake_input,
    )
    ws.send_approval.assert_called_once_with("tc_1", approved=True, reason=None)


@pytest.mark.asyncio
async def test_balucode_yaml_allow_write_auto_approves(capsys):
    from balu_code_cli.config.balucode_yaml import ToolsConfig
    balucode = BaluCodeYaml(project_id=1, server_url="https://x.com",
                            tools=ToolsConfig(allow_write=True))
    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "approval_request", "tool_call_id": "tc_2",
         "tool": "write_file", "args": {}, "risk": "write"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 5, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    inputs = asyncio.Queue()
    await inputs.put("go")
    await inputs.put(EOFError())

    async def fake_input(_p=""): return await inputs.get()

    await run_chat(
        balucode=balucode, api_key="key", yolo=False,
        project_id=1, ws_factory=_make_ws_factory(ws), input_fn=fake_input,
    )
    ws.send_approval.assert_called_once_with("tc_2", approved=True, reason=None)


@pytest.mark.asyncio
async def test_stored_permission_yes_auto_approves(tmp_path):
    from balu_code_cli.config.permissions import PermissionsStore, save_permissions
    store = PermissionsStore()
    store.set("https://x.com", 1, "run_bash", True)
    perms_path = tmp_path / "perms.yaml"
    save_permissions(store, perms_path)

    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "approval_request", "tool_call_id": "tc_3",
         "tool": "run_bash", "args": {"command": "ls"}, "risk": "exec"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 5, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    balucode = BaluCodeYaml(project_id=1, server_url="https://x.com")
    inputs = asyncio.Queue()
    await inputs.put("go")
    await inputs.put(EOFError())

    async def fake_input(_p=""): return await inputs.get()

    await run_chat(
        balucode=balucode, api_key="key", yolo=False, project_id=1,
        ws_factory=_make_ws_factory(ws), input_fn=fake_input,
        perms_path=perms_path,
    )
    ws.send_approval.assert_called_once_with("tc_3", approved=True, reason=None)


@pytest.mark.asyncio
async def test_interactive_y_approves_and_n_denies(tmp_path):
    from balu_code_cli.config.permissions import PermissionsStore, load_permissions
    perms_path = tmp_path / "perms.yaml"

    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "approval_request", "tool_call_id": "tc_4",
         "tool": "write_file", "args": {"path": "a.py"}, "risk": "write"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 5, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    balucode = BaluCodeYaml(project_id=1, server_url="https://x.com")

    user_inputs = asyncio.Queue()
    await user_inputs.put("go")         # REPL prompt
    await user_inputs.put("y")          # approval prompt
    await user_inputs.put(EOFError())   # exit REPL

    async def fake_input(_p=""): return await user_inputs.get()

    await run_chat(
        balucode=balucode, api_key="key", yolo=False, project_id=1,
        ws_factory=_make_ws_factory(ws), input_fn=fake_input,
        perms_path=perms_path,
    )
    ws.send_approval.assert_called_once_with("tc_4", approved=True, reason=None)
    # "y" (not "Y") → not persisted
    store = load_permissions(perms_path)
    assert store.lookup("https://x.com", 1, "write_file") is None


@pytest.mark.asyncio
async def test_interactive_Y_always_persists(tmp_path):
    from balu_code_cli.config.permissions import load_permissions
    perms_path = tmp_path / "perms.yaml"

    events = [
        {"type": "turn_start", "turn_id": "t_1", "model": "llama3", "context_tokens": 5},
        {"type": "approval_request", "tool_call_id": "tc_5",
         "tool": "write_file", "args": {}, "risk": "write"},
        {"type": "turn_end", "turn_id": "t_1", "total_tokens": 5, "iterations": 1, "stop_reason": "done"},
    ]
    ws = _make_fake_ws(events)
    balucode = BaluCodeYaml(project_id=1, server_url="https://x.com")

    user_inputs = asyncio.Queue()
    await user_inputs.put("go")
    await user_inputs.put("Y")   # always
    await user_inputs.put(EOFError())

    async def fake_input(_p=""): return await user_inputs.get()

    await run_chat(
        balucode=balucode, api_key="key", yolo=False, project_id=1,
        ws_factory=_make_ws_factory(ws), input_fn=fake_input,
        perms_path=perms_path,
    )
    ws.send_approval.assert_called_once_with("tc_5", approved=True, reason=None)
    store = load_permissions(perms_path)
    assert store.lookup("https://x.com", 1, "write_file") is True
```

- [ ] **Step 2: Run — verify they fail**

```bash
uv run pytest cli/tests/test_cmd_chat.py -k "approval or yolo or stored or interactive" -v
```

Expected: failures because `_handle_approval` always approves, and `run_chat` doesn't accept `perms_path`.

- [ ] **Step 3: Replace `_handle_approval` and update `run_chat` signature**

In `commands/chat.py`, replace `_handle_approval` and update `run_chat`:

```python
# Add this import at the top:
from pathlib import Path
import json as _json
from rich.panel import Panel
from balu_code_cli.config.permissions import PermissionsStore, load_permissions, save_permissions
from balu_code_cli.config.paths import permissions_yaml as _permissions_yaml


async def _handle_approval(
    ws: BaluCodeWS,
    event,
    balucode: BaluCodeYaml,
    yolo: bool,
    permissions: PermissionsStore,
    perms_path: Path,
    input_fn: InputFn,
) -> None:
    tool_name = event.tool

    # Priority 1: --yolo
    if yolo:
        await ws.send_approval(event.tool_call_id, approved=True, reason=None)
        return

    # Priority 2: .balucode.yaml explicit allow
    if balucode.is_tool_allowed(tool_name):
        await ws.send_approval(event.tool_call_id, approved=True, reason=None)
        return

    # Priority 3: permissions.yaml stored decision
    stored = permissions.lookup(balucode.server_url, balucode.project_id, tool_name)
    if stored is not None:
        await ws.send_approval(event.tool_call_id, approved=stored, reason=None)
        return

    # Priority 4: interactive prompt
    args_preview = _json.dumps(event.args)[:200]
    console.print(Panel(
        f"Tool:  [bold]{tool_name}[/bold]  [dim][risk: {event.risk}][/dim]\n"
        f"Args:  {args_preview}",
        title="Approval required",
    ))

    choice = await input_fn("Allow? [y]es / [n]o / [Y]es always / [N]o always > ")
    choice = choice.strip()
    approved = choice in ("y", "Y")
    always = choice in ("Y", "N")

    if always:
        permissions.set(balucode.server_url, balucode.project_id, tool_name, approved)
        save_permissions(permissions, perms_path)

    await ws.send_approval(event.tool_call_id, approved=approved, reason=None)
```

Update `_dispatch_turn` signature and call to pass `permissions` and `perms_path`:

```python
async def _dispatch_turn(
    ws: BaluCodeWS,
    balucode: BaluCodeYaml,
    yolo: bool,
    permissions: PermissionsStore,
    perms_path: Path,
    input_fn: InputFn,
) -> str | None:
    turn_id = None
    first_token = True

    while True:
        event = await ws.receive()

        if event.type == "turn_start":
            turn_id = event.turn_id

        elif event.type == "token":
            first_token = False
            print(event.content, end="", flush=True)

        elif event.type == "tool_call":
            label = "(auto)" if event.auto_approved else ""
            print(f"\n🔧 {event.tool}({_format_args(event.args)}) {label}", flush=True)

        elif event.type == "tool_result":
            if event.status == "ok":
                print(f"  ✓ ok ({event.bytes_out} bytes)", flush=True)
            else:
                print(f"  ✗ error: {event.error}", flush=True)

        elif event.type == "approval_request":
            await _handle_approval(ws, event, balucode, yolo, permissions, perms_path, input_fn)

        elif event.type == "turn_end":
            print()
            return turn_id

        elif event.type == "error":
            console.print(f"[red]Error [{event.code}]: {event.message}[/red]")

    return turn_id
```

Update `run_chat` signature and body:

```python
async def run_chat(
    balucode: BaluCodeYaml,
    api_key: str,
    yolo: bool,
    project_id: int,
    ws_factory=None,
    input_fn: InputFn = _default_input,
    perms_path: Path | None = None,
) -> None:
    _connect = ws_factory or connect
    _perms_path = perms_path or _permissions_yaml()
    permissions = load_permissions(_perms_path)

    async with _connect(balucode.server_url, api_key, project_id) as ws:
        while True:
            try:
                line = await input_fn("[balu-code] > ")
            except (EOFError, KeyboardInterrupt):
                break

            line = line.strip()
            if not line:
                continue
            if line in (".exit", ".quit"):
                break

            await ws.send_message(line)
            turn_id = None
            try:
                turn_id = await _dispatch_turn(ws, balucode, yolo, permissions, _perms_path, input_fn)
            except KeyboardInterrupt:
                if turn_id:
                    await ws.send_cancel(turn_id)
                    console.print("[yellow]Cancelled[/yellow]")
```

- [ ] **Step 4: Run — verify all chat tests pass**

```bash
uv run pytest cli/tests/test_cmd_chat.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add cli/src/balu_code_cli/commands/chat.py cli/tests/test_cmd_chat.py
git commit -m "feat(cli): add approval flow to chat REPL (permissions tracking)"
```

---

## Task 13: Wire all commands into `__main__.py`

**Files:**
- Modify: `cli/src/balu_code_cli/__main__.py`

- [ ] **Step 1: Write the final `__main__.py`**

Replace `cli/src/balu_code_cli/__main__.py` with the complete wired version:

```python
"""Typer entry point for `balu-code`."""

from __future__ import annotations

import typer

from balu_code_cli import __version__
from balu_code_cli.commands.auth import app as auth_app
from balu_code_cli.commands.chat import app as chat_app
from balu_code_cli.commands.index import app as index_app
from balu_code_cli.commands.init import app as init_app
from balu_code_cli.commands.models import app as models_app

app = typer.Typer(
    name="balu-code",
    no_args_is_help=True,
    add_completion=False,
    help="Balu Code — self-hosted coding agent.",
)
app.add_typer(auth_app, name="auth")
app.add_typer(init_app, name="init")
app.add_typer(models_app, name="models")
app.add_typer(index_app, name="index")
app.add_typer(chat_app, name="chat")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"balu-code {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Balu Code terminal client."""
```

- [ ] **Step 2: Run full CLI test suite**

```bash
uv run pytest cli/tests/ -v
```

Expected: all tests pass (at least 20+).

- [ ] **Step 3: Smoke-test the CLI**

```bash
uv run balu-code --help
```

Expected: shows `auth`, `init`, `models`, `index`, `chat` in the help output.

- [ ] **Step 4: Commit**

```bash
git add cli/src/balu_code_cli/__main__.py
git commit -m "feat(cli): wire all Phase 5a commands into __main__.py"
```

---

## Task 14: Run full test suite + push

**Files:** none — verification only

- [ ] **Step 1: Run the complete project test suite**

```bash
uv run pytest shared/tests/ plugin/tests/ cli/tests/ -q
```

Expected: all pass (291 plugin tests + new CLI tests).

- [ ] **Step 2: Check for any ruff issues**

```bash
uv run ruff check cli/src/balu_code_cli/
```

Expected: no errors.

- [ ] **Step 3: Verify `balu-code --version` works**

```bash
uv run balu-code --version
```

Expected: `balu-code 0.1.0`

- [ ] **Step 4: Push**

```bash
git push origin main
```

Expected: CI green (py 3.11 + 3.12).
