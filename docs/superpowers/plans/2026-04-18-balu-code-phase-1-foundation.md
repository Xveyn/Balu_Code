# Balu Code — Phase 1: Plugin Foundation & Build System

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Balu Code monorepo with a loadable `balu_code` BaluHost plugin that exposes a health endpoint, a `balu-code --version` CLI, shared event schemas, working build scripts that emit a `.bhplugin` + wheel, and GitHub Actions CI that runs pytest + ruff on every push.

**Architecture:** Three-package monorepo (`plugin/`, `cli/`, `shared/`) with one git history. `shared/` is the ground truth for Pydantic event envelopes; both `plugin/` and `cli/` depend on it (editable path dep in dev, vendored into both release artefacts on build). `plugin/` is a `PluginBase` subclass with one `/health` route. `cli/` is a Typer app with one `--version` command. Tests for `plugin/` stub out the `app.plugins.base` import that would normally come from the BaluHost backend. Two scripts (`scripts/build_bhplugin.py`, `scripts/build_wheel.py`) produce the release artefacts deterministically.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI (via BaluHost plugin SDK), Typer, hatchling (build backend for shared + cli), pytest, ruff, GitHub Actions.

---

## File Structure (this phase)

```
Balu_Code/
├── .github/workflows/ci.yml                      ← new
├── .gitignore                                    ← new
├── LICENSE                                       ← new
├── README.md                                     ← new
├── pyproject.toml                                ← new (workspace root, ruff config)
├── scripts/
│   ├── build_bhplugin.py                         ← new
│   └── build_wheel.py                            ← new
├── shared/
│   ├── pyproject.toml                            ← new
│   ├── src/balu_code_shared/
│   │   ├── __init__.py                           ← new (__version__)
│   │   ├── events.py                             ← new (Pydantic envelopes)
│   │   └── py.typed                              ← new (empty marker)
│   └── tests/
│       └── test_events.py                        ← new
├── plugin/
│   ├── plugin.json                               ← new
│   ├── __init__.py                               ← new (BaluCodePlugin)
│   ├── requirements.txt                          ← new
│   ├── pyproject.toml                            ← new (dev-only, for pytest)
│   └── tests/
│       ├── conftest.py                           ← new (baluhost_stub sys.path)
│       ├── fixtures/baluhost_stub/
│       │   └── app/plugins/base.py               ← new (PluginBase + PluginMetadata stub)
│       ├── test_metadata.py                      ← new
│       └── test_health_route.py                  ← new
└── cli/
    ├── pyproject.toml                            ← new
    ├── src/balu_code_cli/
    │   ├── __init__.py                           ← new (__version__)
    │   └── __main__.py                           ← new (Typer app)
    └── tests/
        └── test_version.py                       ← new
```

All files above are **created** in this phase — nothing modified. The repo currently has only `docs/superpowers/specs/2026-04-18-balu-code-design.md` from the brainstorming step.

---

## Task 1: Repo-root files (README, LICENSE, .gitignore, workspace pyproject.toml)

**Files:**
- Create: `README.md`
- Create: `LICENSE`
- Create: `.gitignore`
- Create: `pyproject.toml`

- [ ] **Step 1: Create `README.md`**

```markdown
# Balu Code

Self-hosted coding agent for [BaluHost](https://github.com/Xveyn/Baluhost). Runs against a local Ollama instance and is driven from a terminal CLI.

See [`docs/superpowers/specs/2026-04-18-balu-code-design.md`](docs/superpowers/specs/2026-04-18-balu-code-design.md) for the v1 design.

## Layout

| Dir | Purpose | Distribution |
|---|---|---|
| `plugin/` | BaluHost server plugin (`balu_code`) | `.bhplugin` ZIP → BaluHost Plugin Marketplace |
| `cli/` | Terminal client (`balu-code`) | `balu-code-cli` wheel → PyPI |
| `shared/` | Pydantic event schemas shared by both sides | path-dep in dev, vendored on build |

## Status

Pre-alpha. Phase 1 (foundation) in progress — see `docs/superpowers/plans/`.

## License

MIT — see `LICENSE`.
```

- [ ] **Step 2: Create `LICENSE` (MIT)**

```
MIT License

Copyright (c) 2026 Sven (Xveyn)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 3: Create `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/

# Build artefacts
dist/
build/
*.bhplugin
*.whl

# Virtual environments
.venv/
venv/
env/

# Editor
.vscode/
.idea/
*.swp
.DS_Store

# Plugin-local data
~/.local/share/balu-code/
```

- [ ] **Step 4: Create workspace `pyproject.toml`** (only ruff config; packaging is per-sub-package)

```toml
[tool.ruff]
line-length = 100
target-version = "py311"
extend-exclude = ["plugin/tests/fixtures/baluhost_stub"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]
ignore = ["E501"]  # line length handled by formatter

[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
testpaths = ["shared/tests", "plugin/tests", "cli/tests"]
addopts = "-ra -q --strict-markers"
```

- [ ] **Step 5: Commit**

```bash
git add README.md LICENSE .gitignore pyproject.toml
git commit -m "chore: add README, LICENSE, gitignore, workspace pyproject"
```

---

## Task 2: `shared/` package skeleton

**Files:**
- Create: `shared/pyproject.toml`
- Create: `shared/src/balu_code_shared/__init__.py`
- Create: `shared/src/balu_code_shared/py.typed`

- [ ] **Step 1: Create `shared/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "balu-code-shared"
version = "0.1.0"
description = "Shared Pydantic event and config schemas for Balu Code plugin and CLI."
readme = "../README.md"
license = { file = "../LICENSE" }
requires-python = ">=3.11"
authors = [{ name = "Xveyn" }]
dependencies = [
  "pydantic>=2.6",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.4"]

[tool.hatch.build.targets.wheel]
packages = ["src/balu_code_shared"]
```

- [ ] **Step 2: Create `shared/src/balu_code_shared/__init__.py`**

```python
"""Shared Pydantic schemas used by the Balu Code plugin and CLI."""
from __future__ import annotations

__version__ = "0.1.0"
```

- [ ] **Step 3: Create empty `shared/src/balu_code_shared/py.typed`**

```bash
mkdir -p shared/src/balu_code_shared
touch shared/src/balu_code_shared/py.typed
```

- [ ] **Step 4: Install locally for dev**

Run:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e "shared[dev]"
```
Expected: `Successfully installed balu-code-shared-0.1.0`

- [ ] **Step 5: Commit**

```bash
git add shared/pyproject.toml shared/src/balu_code_shared/__init__.py shared/src/balu_code_shared/py.typed
git commit -m "feat(shared): add package skeleton with version stub"
```

---

## Task 3: `shared/events.py` — minimal Pydantic event envelopes + tests

**Files:**
- Create: `shared/tests/test_events.py`
- Create: `shared/src/balu_code_shared/events.py`

These envelopes are what the WebSocket `/chat` frames deserialise into. Phase 1 only covers the six envelope types needed before the agent loop exists: `UserMessage`, `TurnStart`, `Token`, `TurnEnd`, `Error`, plus a `parse_frame` helper. Tool-related frames (`ToolCall`, `ApprovalRequest`, `ToolResult`) come in Phase 4 when they're actually needed.

- [ ] **Step 1: Write the failing test**

Create `shared/tests/__init__.py` (empty) and `shared/tests/test_events.py`:

```python
"""Tests for balu_code_shared.events."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from balu_code_shared.events import (
    Error,
    Event,
    Token,
    TurnEnd,
    TurnStart,
    UserMessage,
    parse_frame,
)


class TestUserMessage:
    def test_constructs_with_content(self):
        msg = UserMessage(content="hello")
        assert msg.type == "user_message"
        assert msg.content == "hello"

    def test_rejects_empty_content(self):
        with pytest.raises(ValidationError):
            UserMessage(content="")


class TestTurnStart:
    def test_constructs_with_required_fields(self):
        evt = TurnStart(turn_id="t_1", model="qwen2.5-coder:14b", context_tokens=9840)
        assert evt.type == "turn_start"
        assert evt.turn_id == "t_1"
        assert evt.model == "qwen2.5-coder:14b"
        assert evt.context_tokens == 9840

    def test_rejects_negative_context_tokens(self):
        with pytest.raises(ValidationError):
            TurnStart(turn_id="t_1", model="m", context_tokens=-1)


class TestToken:
    def test_constructs_with_content(self):
        evt = Token(content="hello ")
        assert evt.type == "token"
        assert evt.content == "hello "

    def test_allows_empty_token_string(self):
        evt = Token(content="")
        assert evt.content == ""


class TestTurnEnd:
    def test_constructs_with_all_fields(self):
        evt = TurnEnd(
            turn_id="t_1",
            total_tokens=18432,
            iterations=3,
            stop_reason="done",
        )
        assert evt.type == "turn_end"
        assert evt.stop_reason == "done"

    def test_rejects_unknown_stop_reason(self):
        with pytest.raises(ValidationError):
            TurnEnd(
                turn_id="t_1",
                total_tokens=10,
                iterations=1,
                stop_reason="weird",
            )


class TestError:
    def test_constructs_with_code_and_message(self):
        evt = Error(code="ollama_unreachable", message="connection refused")
        assert evt.type == "error"
        assert evt.code == "ollama_unreachable"


class TestParseFrame:
    def test_parses_user_message(self):
        evt = parse_frame({"type": "user_message", "content": "hi"})
        assert isinstance(evt, UserMessage)
        assert evt.content == "hi"

    def test_parses_turn_start(self):
        evt = parse_frame(
            {"type": "turn_start", "turn_id": "t_1", "model": "m", "context_tokens": 42}
        )
        assert isinstance(evt, TurnStart)

    def test_rejects_unknown_type(self):
        with pytest.raises(ValidationError):
            parse_frame({"type": "mystery", "x": 1})

    def test_rejects_missing_type(self):
        with pytest.raises(ValidationError):
            parse_frame({"content": "no type field"})


def test_event_union_includes_all_six():
    import typing

    members = typing.get_args(Event)
    names = {m.model_fields["type"].default for m in members}
    assert names == {"user_message", "turn_start", "token", "turn_end", "error"}
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest shared/tests/test_events.py -v`
Expected: `ModuleNotFoundError: No module named 'balu_code_shared.events'`

- [ ] **Step 3: Implement `shared/src/balu_code_shared/events.py`**

```python
"""WebSocket event envelopes shared by the Balu Code plugin and CLI.

Each envelope has a literal ``type`` discriminator. ``parse_frame`` uses
a Pydantic discriminated union to dispatch an incoming dict to the right
model, which is the single source of truth both sides rely on.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _FrozenBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class UserMessage(_FrozenBase):
    type: Literal["user_message"] = "user_message"
    content: str = Field(..., min_length=1)


class TurnStart(_FrozenBase):
    type: Literal["turn_start"] = "turn_start"
    turn_id: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    context_tokens: int = Field(..., ge=0)


class Token(_FrozenBase):
    type: Literal["token"] = "token"
    content: str


StopReason = Literal["done", "max_iter", "error", "cancelled"]


class TurnEnd(_FrozenBase):
    type: Literal["turn_end"] = "turn_end"
    turn_id: str = Field(..., min_length=1)
    total_tokens: int = Field(..., ge=0)
    iterations: int = Field(..., ge=0)
    stop_reason: StopReason


class Error(_FrozenBase):
    type: Literal["error"] = "error"
    code: str = Field(..., min_length=1)
    message: str


Event = Annotated[
    Union[UserMessage, TurnStart, Token, TurnEnd, Error],
    Field(discriminator="type"),
]


_adapter: TypeAdapter[Event] = TypeAdapter(Event)


def parse_frame(data: dict[str, Any]) -> Event:
    """Deserialise a dict-shaped WebSocket frame into the matching Event model."""
    return _adapter.validate_python(data)


__all__ = [
    "Error",
    "Event",
    "StopReason",
    "Token",
    "TurnEnd",
    "TurnStart",
    "UserMessage",
    "parse_frame",
]
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest shared/tests/test_events.py -v`
Expected: 13 passed

- [ ] **Step 5: Run ruff**

Run: `ruff check shared/ && ruff format --check shared/`
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add shared/src/balu_code_shared/events.py shared/tests/__init__.py shared/tests/test_events.py
git commit -m "feat(shared): add v1 WebSocket event envelopes (UserMessage, TurnStart, Token, TurnEnd, Error) with parse_frame"
```

---

## Task 4: `plugin/` bootstrap — `plugin.json`, `requirements.txt`, dev `pyproject.toml`, empty `__init__.py`

**Files:**
- Create: `plugin/plugin.json`
- Create: `plugin/requirements.txt`
- Create: `plugin/pyproject.toml`
- Create: `plugin/__init__.py`

The `plugin.json` is the single manifest read by the BaluHost marketplace. The `pyproject.toml` here is **dev-only** (for `pytest` to discover `plugin/`); it is not published as a package — the plugin ships as a `.bhplugin` zip.

- [ ] **Step 1: Create `plugin/plugin.json`**

```json
{
  "manifest_version": 1,
  "name": "balu_code",
  "version": "0.1.0",
  "display_name": "Balu Code",
  "description": "Self-hosted coding agent backed by Ollama. Provides a terminal CLI and a web settings panel.",
  "author": "Xveyn",
  "category": "general",
  "homepage": "https://github.com/Xveyn/Balu_Code",
  "min_baluhost_version": "1.30.0",
  "required_permissions": [
    "file:read",
    "file:write",
    "file:delete",
    "system:execute",
    "system:info",
    "network:outbound",
    "db:read",
    "db:write",
    "event:emit",
    "task:background"
  ],
  "plugin_dependencies": [],
  "python_requirements": [
    "httpx>=0.27",
    "pydantic>=2.6"
  ],
  "entrypoint": "__init__.py",
  "ui": { "bundle": "ui/bundle.js", "styles": null }
}
```

Note: `python_requirements` covers only what Phase 1 actually imports. `tree-sitter`, `sqlite-vec`, `pyyaml`, etc. are added in later phases when they're used.

- [ ] **Step 2: Create `plugin/requirements.txt`** (mirror of the `python_requirements` above for pip-based dev installs)

```
httpx>=0.27
pydantic>=2.6
```

- [ ] **Step 3: Create `plugin/pyproject.toml`** (dev-only)

```toml
[project]
name = "balu-code-plugin-dev"
version = "0.0.0"
description = "Dev-only metadata so pytest can import plugin/ and its tests."
requires-python = ">=3.11"
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.6",
  "fastapi>=0.110",
  "balu-code-shared",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "ruff>=0.4",
]

[tool.setuptools]
py-modules = []
```

- [ ] **Step 4: Create empty `plugin/__init__.py`**

```python
"""Balu Code BaluHost plugin.

Loaded at BaluHost startup by PluginManager via plugin.json / entrypoint.
"""
from __future__ import annotations
```

(The `BaluCodePlugin` class is added in Task 5.)

- [ ] **Step 5: Install dev deps**

Run: `pip install -e "plugin[dev]"`
Expected: installs without errors.

- [ ] **Step 6: Commit**

```bash
git add plugin/plugin.json plugin/requirements.txt plugin/pyproject.toml plugin/__init__.py
git commit -m "feat(plugin): add plugin.json, requirements, dev pyproject, empty __init__"
```

---

## Task 5: `plugin/tests/conftest.py` + BaluHost stub

**Files:**
- Create: `plugin/tests/__init__.py`
- Create: `plugin/tests/conftest.py`
- Create: `plugin/tests/fixtures/__init__.py`
- Create: `plugin/tests/fixtures/baluhost_stub/app/__init__.py`
- Create: `plugin/tests/fixtures/baluhost_stub/app/plugins/__init__.py`
- Create: `plugin/tests/fixtures/baluhost_stub/app/plugins/base.py`

Tests need `from app.plugins.base import PluginBase, PluginMetadata` to resolve, but that module lives in the separate BaluHost repo. The stub provides exactly the surface `plugin/__init__.py` imports, so tests don't need BaluHost installed.

- [ ] **Step 1: Create empty `__init__.py` files**

```bash
touch plugin/tests/__init__.py
touch plugin/tests/fixtures/__init__.py
mkdir -p plugin/tests/fixtures/baluhost_stub/app/plugins
touch plugin/tests/fixtures/baluhost_stub/app/__init__.py
touch plugin/tests/fixtures/baluhost_stub/app/plugins/__init__.py
```

- [ ] **Step 2: Create `plugin/tests/fixtures/baluhost_stub/app/plugins/base.py`**

```python
"""Stub of BaluHost's app.plugins.base for use in balu_code plugin tests.

Mirrors only the surface area balu_code imports. Keep in sync with
/opt/baluhost/backend/app/plugins/base.py when that file changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict, List, Optional

from pydantic import BaseModel, Field


class PluginMetadata(BaseModel):
    name: str
    version: str
    display_name: str
    description: str
    author: str
    required_permissions: List[str] = Field(default_factory=list)
    category: str = "general"
    homepage: Optional[str] = None
    min_baluhost_version: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)


@dataclass
class BackgroundTaskSpec:
    name: str
    func: Callable[[], Coroutine[Any, Any, None]]
    interval_seconds: float
    run_on_startup: bool = True


class PluginBase(ABC):
    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        ...

    def get_router(self):  # type: ignore[no-untyped-def]
        return None

    async def on_startup(self) -> None:
        return None

    async def on_shutdown(self) -> None:
        return None

    def get_background_tasks(self) -> List[BackgroundTaskSpec]:
        return []

    def get_config_schema(self) -> Optional[type]:
        return None

    def get_default_config(self) -> Dict[str, Any]:
        return {}
```

- [ ] **Step 3: Create `plugin/tests/conftest.py`**

```python
"""Pytest bootstrap for plugin tests.

Inserts the BaluHost stub onto sys.path so that ``from app.plugins.base ...``
resolves to a local fixture rather than requiring BaluHost to be installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

_STUB_DIR = Path(__file__).parent / "fixtures" / "baluhost_stub"
sys.path.insert(0, str(_STUB_DIR))

# Sanity: the stub must import cleanly before any test collection runs.
from app.plugins.base import PluginBase, PluginMetadata  # noqa: E402,F401
```

- [ ] **Step 4: Verify the stub is importable**

Run: `cd plugin && python -c "import sys; sys.path.insert(0, 'tests/fixtures/baluhost_stub'); from app.plugins.base import PluginBase; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add plugin/tests/__init__.py plugin/tests/conftest.py plugin/tests/fixtures/
git commit -m "test(plugin): add BaluHost stub and pytest conftest"
```

---

## Task 6: `BaluCodePlugin` class with metadata + test

**Files:**
- Create: `plugin/tests/test_metadata.py`
- Modify: `plugin/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `plugin/tests/test_metadata.py`:

```python
"""Tests for BaluCodePlugin metadata."""
from __future__ import annotations

import json
from pathlib import Path

from plugin import BaluCodePlugin  # noqa: F401 — package root is `plugin/`


def test_plugin_name_is_balu_code():
    p = BaluCodePlugin()
    assert p.metadata.name == "balu_code"


def test_plugin_version_matches_plugin_json():
    p = BaluCodePlugin()
    manifest = json.loads((Path(__file__).parent.parent / "plugin.json").read_text())
    assert p.metadata.version == manifest["version"]


def test_plugin_required_permissions_match_manifest():
    p = BaluCodePlugin()
    manifest = json.loads((Path(__file__).parent.parent / "plugin.json").read_text())
    assert set(p.metadata.required_permissions) == set(manifest["required_permissions"])


def test_plugin_display_name():
    p = BaluCodePlugin()
    assert p.metadata.display_name == "Balu Code"


def test_plugin_category_is_general():
    p = BaluCodePlugin()
    assert p.metadata.category == "general"
```

Note: the test imports `from plugin import BaluCodePlugin`. Because `plugin/` is not a proper installed package (only a dev pyproject), pytest needs to discover it via `rootdir` and the `plugin/__init__.py`. Run pytest from the repo root: `pytest plugin/tests -v`.

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd /home/sven/projects/plugins/Balu_Code && pytest plugin/tests/test_metadata.py -v`
Expected: `ImportError: cannot import name 'BaluCodePlugin' from 'plugin'` (or ModuleNotFoundError for `plugin`)

If pytest can't find `plugin/` as a package, add to the workspace `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
pythonpath = ["."]
```

- [ ] **Step 3: Implement `plugin/__init__.py`**

Replace the empty file with:

```python
"""Balu Code BaluHost plugin.

Loaded at BaluHost startup by PluginManager. Exposes a FastAPI router at
/api/plugins/balu_code/ — currently only /health; real routes come in
later phases.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.plugins.base import PluginBase, PluginMetadata

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


class BaluCodePlugin(PluginBase):
    """Main plugin class. Metadata is read from plugin.json at import time."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=_MANIFEST["name"],
            version=_MANIFEST["version"],
            display_name=_MANIFEST["display_name"],
            description=_MANIFEST["description"],
            author=_MANIFEST["author"],
            required_permissions=list(_MANIFEST["required_permissions"]),
            category=_MANIFEST.get("category", "general"),
            homepage=_MANIFEST.get("homepage"),
            min_baluhost_version=_MANIFEST.get("min_baluhost_version"),
            dependencies=list(_MANIFEST.get("plugin_dependencies", [])),
        )


__all__ = ["BaluCodePlugin"]
```

- [ ] **Step 4: Add pythonpath config so `from plugin import BaluCodePlugin` resolves**

Edit the workspace `pyproject.toml` — change the `[tool.pytest.ini_options]` section to:

```toml
[tool.pytest.ini_options]
testpaths = ["shared/tests", "plugin/tests", "cli/tests"]
pythonpath = ["."]
addopts = "-ra -q --strict-markers"
```

- [ ] **Step 5: Run the test and verify it passes**

Run: `pytest plugin/tests/test_metadata.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add plugin/__init__.py plugin/tests/test_metadata.py pyproject.toml
git commit -m "feat(plugin): add BaluCodePlugin class reading metadata from plugin.json"
```

---

## Task 7: `/health` route + test

**Files:**
- Create: `plugin/tests/test_health_route.py`
- Modify: `plugin/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `plugin/tests/test_health_route.py`:

```python
"""Tests for the /health route."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin import BaluCodePlugin


def _client() -> TestClient:
    """Mount the plugin's router on a bare FastAPI app (mirrors what BaluHost does)."""
    app = FastAPI()
    plugin = BaluCodePlugin()
    router = plugin.get_router()
    assert router is not None, "plugin must provide a router"
    app.include_router(router, prefix="/api/plugins/balu_code")
    return TestClient(app)


def test_health_returns_200():
    r = _client().get("/api/plugins/balu_code/health")
    assert r.status_code == 200


def test_health_body_shape():
    r = _client().get("/api/plugins/balu_code/health")
    body = r.json()
    assert body["status"] == "ok"
    assert body["plugin"] == "balu_code"
    assert body["version"]
    assert isinstance(body["version"], str)
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest plugin/tests/test_health_route.py -v`
Expected: `AssertionError: plugin must provide a router`

- [ ] **Step 3: Replace `plugin/__init__.py` with the version that adds `_build_router` and wires it into `BaluCodePlugin.get_router`**

```python
"""Balu Code BaluHost plugin.

Loaded at BaluHost startup by PluginManager. Exposes a FastAPI router at
/api/plugins/balu_code/ — currently only /health; real routes come in
later phases.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from app.plugins.base import PluginBase, PluginMetadata

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


def _build_router() -> APIRouter:
    """Build the FastAPI router served under /api/plugins/balu_code."""
    router = APIRouter()

    @router.get("/health", tags=["balu_code"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "plugin": _MANIFEST["name"],
            "version": _MANIFEST["version"],
        }

    return router


class BaluCodePlugin(PluginBase):
    """Main plugin class. Metadata read from plugin.json at import time."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=_MANIFEST["name"],
            version=_MANIFEST["version"],
            display_name=_MANIFEST["display_name"],
            description=_MANIFEST["description"],
            author=_MANIFEST["author"],
            required_permissions=list(_MANIFEST["required_permissions"]),
            category=_MANIFEST.get("category", "general"),
            homepage=_MANIFEST.get("homepage"),
            min_baluhost_version=_MANIFEST.get("min_baluhost_version"),
            dependencies=list(_MANIFEST.get("plugin_dependencies", [])),
        )

    def get_router(self) -> APIRouter:
        return _build_router()


__all__ = ["BaluCodePlugin"]
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest plugin/tests/test_health_route.py -v`
Expected: 2 passed

- [ ] **Step 5: Run the full plugin test suite**

Run: `pytest plugin/tests -v`
Expected: 7 passed (5 metadata + 2 health)

- [ ] **Step 6: Commit**

```bash
git add plugin/__init__.py plugin/tests/test_health_route.py
git commit -m "feat(plugin): add /health route and router wiring"
```

---

## Task 8: CLI skeleton — `balu-code --version`

**Files:**
- Create: `cli/pyproject.toml`
- Create: `cli/src/balu_code_cli/__init__.py`
- Create: `cli/src/balu_code_cli/__main__.py`
- Create: `cli/tests/__init__.py`
- Create: `cli/tests/test_version.py`

- [ ] **Step 1: Create `cli/pyproject.toml`**

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
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "ruff>=0.4",
]

[project.scripts]
balu-code = "balu_code_cli.__main__:app"

[tool.hatch.build.targets.wheel]
packages = ["src/balu_code_cli"]
```

- [ ] **Step 2: Create `cli/src/balu_code_cli/__init__.py`**

```python
"""Balu Code terminal client."""
from __future__ import annotations

__version__ = "0.1.0"
```

- [ ] **Step 3: Write the failing test**

Create `cli/tests/__init__.py` (empty) and `cli/tests/test_version.py`:

```python
"""Tests for `balu-code --version`."""
from __future__ import annotations

from typer.testing import CliRunner

from balu_code_cli import __version__
from balu_code_cli.__main__ import app


def test_version_flag_prints_version_and_exits_zero():
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_no_args_prints_help_and_exits_zero():
    runner = CliRunner()
    result = runner.invoke(app, [])
    # typer defaults: no command = show help, exit 0 when no_args_is_help=True
    assert result.exit_code in (0, 2)
    assert "balu-code" in result.stdout.lower() or "usage" in result.stdout.lower()


def test_version_matches_package_version():
    # sanity: CLI __version__ string is sane
    import re

    assert re.match(r"^\d+\.\d+\.\d+", __version__)
```

- [ ] **Step 4: Run the test and verify it fails**

Run: `pytest cli/tests/test_version.py -v`
Expected: `ModuleNotFoundError: No module named 'balu_code_cli.__main__'`

- [ ] **Step 5: Implement `cli/src/balu_code_cli/__main__.py`**

```python
"""Typer entry point for `balu-code`.

Phase 1 only registers the top-level ``--version`` callback. Real
subcommands (auth, init, chat, …) land in later phases.
"""
from __future__ import annotations

import typer

from balu_code_cli import __version__

app = typer.Typer(
    name="balu-code",
    no_args_is_help=True,
    add_completion=False,
    help="Balu Code — self-hosted coding agent.",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"balu-code {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Balu Code terminal client."""
```

- [ ] **Step 6: Install the CLI in dev mode**

Run: `pip install -e "cli[dev]"`
Expected: `Successfully installed balu-code-cli-0.1.0`.

- [ ] **Step 7: Run the test and verify it passes**

Run: `pytest cli/tests/test_version.py -v`
Expected: 3 passed

- [ ] **Step 8: Smoke-test the installed console script**

Run: `balu-code --version`
Expected: `balu-code 0.1.0`

- [ ] **Step 9: Commit**

```bash
git add cli/pyproject.toml cli/src/ cli/tests/
git commit -m "feat(cli): add typer skeleton with --version flag"
```

---

## Task 9: `scripts/build_bhplugin.py`

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/build_bhplugin.py`
- Create: `scripts/tests/__init__.py`
- Create: `scripts/tests/test_build_bhplugin.py`

The script zips `plugin/*` (minus `tests/`, `pyproject.toml`, `__pycache__`) plus the `balu_code_shared` source tree (vendored so the marketplace artefact has no path-deps at runtime) into `dist/balu_code-<version>.bhplugin`. It also writes `dist/balu_code-<version>.bhplugin.sha256`.

- [ ] **Step 1: Write the failing test**

Create `scripts/__init__.py` (empty), `scripts/tests/__init__.py` (empty), `scripts/tests/test_build_bhplugin.py`:

```python
"""Tests for the .bhplugin build script."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.build_bhplugin import build_bhplugin


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_build_produces_zip_with_plugin_json(tmp_path):
    artefact = build_bhplugin(REPO_ROOT, tmp_path)
    assert artefact.exists()
    assert artefact.suffix == ".bhplugin"
    with zipfile.ZipFile(artefact) as zf:
        names = set(zf.namelist())
    assert "plugin.json" in names


def test_build_includes_init_and_requirements(tmp_path):
    artefact = build_bhplugin(REPO_ROOT, tmp_path)
    with zipfile.ZipFile(artefact) as zf:
        names = set(zf.namelist())
    assert "__init__.py" in names
    assert "requirements.txt" in names


def test_build_vendors_balu_code_shared(tmp_path):
    artefact = build_bhplugin(REPO_ROOT, tmp_path)
    with zipfile.ZipFile(artefact) as zf:
        names = set(zf.namelist())
    assert any(n.startswith("balu_code_shared/") and n.endswith(".py") for n in names), (
        "expected vendored balu_code_shared/ tree"
    )
    assert "balu_code_shared/events.py" in names


def test_build_excludes_tests_and_dev_pyproject(tmp_path):
    artefact = build_bhplugin(REPO_ROOT, tmp_path)
    with zipfile.ZipFile(artefact) as zf:
        names = set(zf.namelist())
    assert not any(n.startswith("tests/") for n in names)
    assert "pyproject.toml" not in names
    assert not any(n.endswith("__pycache__/") for n in names)


def test_build_emits_sha256_sidecar(tmp_path):
    artefact = build_bhplugin(REPO_ROOT, tmp_path)
    sidecar = artefact.with_suffix(artefact.suffix + ".sha256")
    assert sidecar.exists()
    expected = hashlib.sha256(artefact.read_bytes()).hexdigest()
    assert sidecar.read_text().strip().split()[0] == expected


def test_artefact_filename_includes_version(tmp_path):
    artefact = build_bhplugin(REPO_ROOT, tmp_path)
    manifest = json.loads((REPO_ROOT / "plugin" / "plugin.json").read_text())
    assert manifest["version"] in artefact.name
    assert artefact.name.startswith("balu_code-")
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest scripts/tests/test_build_bhplugin.py -v`
Expected: `ModuleNotFoundError: No module named 'scripts.build_bhplugin'`

- [ ] **Step 3: Implement `scripts/build_bhplugin.py`**

```python
"""Build the `.bhplugin` archive from plugin/ + vendored shared/.

Usage (CLI):
    python -m scripts.build_bhplugin --repo-root . --dist dist/

Importable:
    from scripts.build_bhplugin import build_bhplugin
    artefact = build_bhplugin(Path("."), Path("dist"))
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


_EXCLUDE_TOPLEVEL = {"tests", "pyproject.toml", "__pycache__"}
_EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _should_include(relpath: Path) -> bool:
    parts = relpath.parts
    if not parts:
        return False
    if parts[0] in _EXCLUDE_TOPLEVEL:
        return False
    if any(p == "__pycache__" for p in parts):
        return False
    if relpath.suffix in _EXCLUDE_SUFFIXES:
        return False
    return True


def _iter_plugin_files(plugin_dir: Path):
    for p in plugin_dir.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(plugin_dir)
        if _should_include(rel):
            yield p, rel


def _iter_shared_files(shared_dir: Path):
    """Yield files under shared/src/balu_code_shared to be vendored at archive root."""
    src_root = shared_dir / "src" / "balu_code_shared"
    for p in src_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix in _EXCLUDE_SUFFIXES:
            continue
        if "__pycache__" in p.parts:
            continue
        rel = Path("balu_code_shared") / p.relative_to(src_root)
        yield p, rel


def build_bhplugin(repo_root: Path, dist_dir: Path) -> Path:
    """Produce `<dist>/balu_code-<version>.bhplugin` and its .sha256 sidecar.

    Returns the path to the .bhplugin file.
    """
    plugin_dir = repo_root / "plugin"
    shared_dir = repo_root / "shared"
    manifest = json.loads((plugin_dir / "plugin.json").read_text())
    version = manifest["version"]
    name = manifest["name"]

    dist_dir.mkdir(parents=True, exist_ok=True)
    artefact = dist_dir / f"{name}-{version}.bhplugin"
    if artefact.exists():
        artefact.unlink()

    with zipfile.ZipFile(artefact, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, rel in _iter_plugin_files(plugin_dir):
            zf.write(src, rel.as_posix())
        for src, rel in _iter_shared_files(shared_dir):
            zf.write(src, rel.as_posix())

    digest = hashlib.sha256(artefact.read_bytes()).hexdigest()
    sidecar = artefact.with_suffix(artefact.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {artefact.name}\n")

    return artefact


def _main() -> None:
    parser = argparse.ArgumentParser(description="Build balu_code .bhplugin archive")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    args = parser.parse_args()
    out = build_bhplugin(args.repo_root.resolve(), args.dist.resolve())
    print(f"Built {out}")


if __name__ == "__main__":
    _main()
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest scripts/tests/test_build_bhplugin.py -v`
Expected: 6 passed

- [ ] **Step 5: Smoke-test via CLI**

Run: `python -m scripts.build_bhplugin --repo-root . --dist dist/`
Expected: `Built .../dist/balu_code-0.1.0.bhplugin`; `ls dist/` shows both file and `.sha256` sidecar.

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/build_bhplugin.py scripts/tests/__init__.py scripts/tests/test_build_bhplugin.py
git commit -m "feat(scripts): add build_bhplugin.py with tests"
```

---

## Task 10: `scripts/build_wheel.py`

**Files:**
- Create: `scripts/build_wheel.py`
- Create: `scripts/tests/test_build_wheel.py`

The wheel build copies `shared/src/balu_code_shared/` into `cli/src/` as a **vendored** subpackage so the published wheel has no external `balu-code-shared` dependency. After the build, the vendored copy is removed to keep the repo clean. The actual build is delegated to the `build` PyPA tool (already a standard part of the toolchain).

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/test_build_wheel.py`:

```python
"""Tests for the wheel build script."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.build_wheel import build_wheel


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_build_produces_wheel(tmp_path):
    artefact = build_wheel(REPO_ROOT, tmp_path)
    assert artefact.exists()
    assert artefact.suffix == ".whl"


def test_wheel_includes_main_module(tmp_path):
    artefact = build_wheel(REPO_ROOT, tmp_path)
    with zipfile.ZipFile(artefact) as zf:
        names = set(zf.namelist())
    assert any(n.endswith("balu_code_cli/__main__.py") for n in names)


def test_wheel_vendors_shared(tmp_path):
    artefact = build_wheel(REPO_ROOT, tmp_path)
    with zipfile.ZipFile(artefact) as zf:
        names = set(zf.namelist())
    # vendored as nested package `balu_code_cli._vendored.balu_code_shared`
    assert any("balu_code_shared/events.py" in n for n in names)


def test_cleanup_removes_vendored_dir_after_build(tmp_path):
    build_wheel(REPO_ROOT, tmp_path)
    vendored = REPO_ROOT / "cli" / "src" / "balu_code_cli" / "_vendored"
    assert not vendored.exists(), "vendored directory must be removed post-build"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest scripts/tests/test_build_wheel.py -v`
Expected: `ModuleNotFoundError: No module named 'scripts.build_wheel'`

- [ ] **Step 3: Implement `scripts/build_wheel.py`**

```python
"""Build the `balu-code-cli` wheel with vendored balu_code_shared.

The released wheel must not have a runtime dependency on the separate
`balu-code-shared` package (it lives in the same monorepo). We copy the
shared source into `cli/src/balu_code_cli/_vendored/balu_code_shared/`
right before the build and remove it right after, so source control
never contains the vendored tree.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _copy_vendored(shared_dir: Path, cli_src: Path) -> Path:
    src = shared_dir / "src" / "balu_code_shared"
    dest = cli_src / "balu_code_cli" / "_vendored"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "__init__.py").write_text(
        "\"\"\"Auto-vendored at build time; do not commit.\"\"\"\n"
    )
    target = dest / "balu_code_shared"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src, target)
    return dest


def _remove_vendored(vendored_dir: Path) -> None:
    if vendored_dir.exists():
        shutil.rmtree(vendored_dir)


def _patch_pyproject_dependency(cli_pyproject: Path) -> str:
    """Temporarily strip the `balu-code-shared` dep from cli/pyproject.toml.

    Returns the original text so we can restore it.
    """
    original = cli_pyproject.read_text()
    patched = "\n".join(
        line
        for line in original.splitlines()
        if line.strip() != '"balu-code-shared",'
    )
    cli_pyproject.write_text(patched + "\n")
    return original


def _restore_pyproject(cli_pyproject: Path, original: str) -> None:
    cli_pyproject.write_text(original)


def build_wheel(repo_root: Path, dist_dir: Path) -> Path:
    """Build cli/ wheel with vendored shared. Returns the wheel path."""
    shared_dir = repo_root / "shared"
    cli_dir = repo_root / "cli"
    cli_src = cli_dir / "src"
    cli_pyproject = cli_dir / "pyproject.toml"

    dist_dir.mkdir(parents=True, exist_ok=True)

    vendored = _copy_vendored(shared_dir, cli_src)
    original_pyproject = _patch_pyproject_dependency(cli_pyproject)
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--outdir",
                str(dist_dir.resolve()),
                str(cli_dir),
            ],
            check=True,
        )
    finally:
        _remove_vendored(vendored)
        _restore_pyproject(cli_pyproject, original_pyproject)

    wheels = sorted(dist_dir.glob("balu_code_cli-*.whl"))
    if not wheels:
        raise RuntimeError(f"no wheel found in {dist_dir}")
    return wheels[-1]


def _main() -> None:
    parser = argparse.ArgumentParser(description="Build balu-code-cli wheel")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    args = parser.parse_args()
    out = build_wheel(args.repo_root.resolve(), args.dist.resolve())
    print(f"Built {out}")


if __name__ == "__main__":
    _main()
```

- [ ] **Step 4: Install `build` so the script's subprocess call works**

Run: `pip install build`
Expected: installs the PyPA `build` package.

- [ ] **Step 5: Run the test and verify it passes**

Run: `pytest scripts/tests/test_build_wheel.py -v`
Expected: 4 passed

- [ ] **Step 6: Smoke-test via CLI**

Run: `python -m scripts.build_wheel --repo-root . --dist dist/`
Expected: `Built .../dist/balu_code_cli-0.1.0-py3-none-any.whl`; confirm `cli/src/balu_code_cli/_vendored/` no longer exists.

- [ ] **Step 7: Commit**

```bash
git add scripts/build_wheel.py scripts/tests/test_build_wheel.py
git commit -m "feat(scripts): add build_wheel.py vendoring shared/ into the wheel"
```

---

## Task 11: GitHub Actions CI — `.github/workflows/ci.yml`

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    name: pytest + ruff (py ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Install all dev deps
        run: |
          python -m pip install --upgrade pip
          pip install -e "shared[dev]"
          pip install -e "plugin[dev]"
          pip install -e "cli[dev]"
          pip install build

      - name: Ruff lint
        run: ruff check .

      - name: Ruff format check
        run: ruff format --check .

      - name: Pytest
        run: pytest -v

      - name: Build artefacts
        run: |
          python -m scripts.build_bhplugin --repo-root . --dist dist/
          python -m scripts.build_wheel --repo-root . --dist dist/

      - name: Upload artefacts
        if: matrix.python-version == '3.12'
        uses: actions/upload-artifact@v4
        with:
          name: balu_code-artefacts
          path: dist/
          retention-days: 14
```

- [ ] **Step 2: Verify the workflow file is syntactically valid YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no exception (exit 0).

- [ ] **Step 3: Locally replicate what CI will run**

Run the exact shell sequence from the workflow:
```bash
pip install -e "shared[dev]" -e "plugin[dev]" -e "cli[dev]" build
ruff check .
ruff format --check .
pytest -v
python -m scripts.build_bhplugin --repo-root . --dist dist/
python -m scripts.build_wheel --repo-root . --dist dist/
```
Expected:
- ruff: no findings
- pytest: all tests pass (around 18–20 total across the 3 test directories)
- build scripts: `dist/balu_code-0.1.0.bhplugin`, `dist/balu_code-0.1.0.bhplugin.sha256`, `dist/balu_code_cli-0.1.0-py3-none-any.whl`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow (ruff + pytest + build artefacts)"
```

---

## Task 12: End-to-end smoke test — install `.bhplugin` locally into a BaluHost checkout

**Files:** none created or modified in this task — this is a manual verification plus a single documentation file.
- Create: `docs/phase-1-verification.md`

This task confirms the built artefact actually loads inside BaluHost. We sideload it into the dev BaluHost tree rather than going through the marketplace installer.

- [ ] **Step 1: Extract the built `.bhplugin` into BaluHost's installed-plugins dir**

Run:
```bash
cd /opt/baluhost/backend/app/plugins/installed
# adjust the path to wherever your dev BaluHost copy lives — this is the prod path
sudo rm -rf balu_code   # remove any previous attempt
sudo mkdir balu_code
sudo unzip /home/sven/projects/plugins/Balu_Code/dist/balu_code-0.1.0.bhplugin -d balu_code
sudo chown -R sven:sven balu_code
```
Expected: `balu_code/` contains `plugin.json`, `__init__.py`, `requirements.txt`, `balu_code_shared/…`.

- [ ] **Step 2: Install the plugin's own requirements into BaluHost's venv**

Run:
```bash
cd /opt/baluhost/backend
source .venv/bin/activate
pip install -r app/plugins/installed/balu_code/requirements.txt
```
Expected: httpx and pydantic already present (or installed).

- [ ] **Step 3: Restart the BaluHost backend**

Run: `sudo systemctl restart baluhost-backend` (or the dev runner, whichever applies).

- [ ] **Step 4: Enable the plugin via the admin UI or SQL**

Via SQL (fastest):
```bash
sudo -u baluhost psql baluhost -c "
INSERT INTO installed_plugins (name, version, display_name, is_enabled, granted_permissions, config, installed_at)
VALUES (
    'balu_code', '0.1.0', 'Balu Code', true,
    '[\"file:read\",\"file:write\",\"file:delete\",\"system:execute\",\"system:info\",\"network:outbound\",\"db:read\",\"db:write\",\"event:emit\",\"task:background\"]'::jsonb,
    '{}'::jsonb,
    now()
)
ON CONFLICT (name) DO UPDATE SET is_enabled = true, version = EXCLUDED.version;
"
```
Expected: `INSERT 0 1` or `UPDATE 1`.

- [ ] **Step 5: Hit `/health`**

Run:
```bash
curl -s -H "Authorization: Bearer <your-api-key>" https://nas.example.com/api/plugins/balu_code/health | jq .
```
Expected:
```json
{"status":"ok","plugin":"balu_code","version":"0.1.0"}
```

- [ ] **Step 6: Document the verification result**

Create `docs/phase-1-verification.md`:

```markdown
# Phase 1 verification — 2026-04-18

## Environment

- BaluHost: (git SHA of the dev checkout you sideloaded into)
- Python: (output of `python --version`)
- GPU/CPU: RX 7900 XT (ROCm), inference not exercised in Phase 1

## Checks

- [x] `pytest -v` — N tests pass locally
- [x] `ruff check .` — no findings
- [x] `ruff format --check .` — no findings
- [x] `python -m scripts.build_bhplugin` produces `dist/balu_code-0.1.0.bhplugin` + sha256 sidecar
- [x] `python -m scripts.build_wheel` produces `dist/balu_code_cli-0.1.0-py3-none-any.whl`
- [x] Sideloaded `.bhplugin` into `/opt/baluhost/backend/app/plugins/installed/balu_code/`
- [x] `GET /api/plugins/balu_code/health` returns `{"status":"ok","plugin":"balu_code","version":"0.1.0"}`
- [x] `balu-code --version` prints `balu-code 0.1.0`
- [x] GitHub Actions: first run on PR to `main` green (link: …)

## Known issues carried into Phase 2

- (fill in any surprises encountered during verification)
```

- [ ] **Step 7: Commit**

```bash
git add docs/phase-1-verification.md
git commit -m "docs: add Phase 1 verification checklist and record"
```

---

## Phase 1 definition of done

- All 12 tasks complete and pushed.
- CI green on `main`.
- `curl .../api/plugins/balu_code/health` → `{"status":"ok",…}` on the dev BaluHost.
- `balu-code --version` → `balu-code 0.1.0` on the developer's laptop.

## What comes next (future plans, not this plan)

Only Phase 1 is committed here. Once Phase 1 merges, write these one at a time:

- **Phase 2 — Ollama client + project store + basic routes.** `services/ollama_client.py` (streaming `/api/chat`, `/api/embeddings`, `/api/tags`), `services/project_store.py` (SQLite, `projects` + `repo_map_cache` tables), `POST|GET|DELETE /projects`, `GET /models`. Tests use a fake Ollama over `httpx.MockTransport`.
- **Phase 3 — Repo-Map + RAG.** Tree-sitter walker and budget-aware formatter; sqlite-vec chunk store and embedding pipeline; `POST /projects/{id}/index`, `GET /projects/{id}/repo_map`. Fixture projects in py/ts/go.
- **Phase 4 — Agent loop + tools + WebSocket `/chat`.** `services/agent_loop.py`, tool registry, v1 tools (`read_file`, `glob`, `grep`, `write_file`, `apply_patch`, `run_bash`, `web_fetch`), `WS /chat`, context-assembler. End-to-end tests with a scripted fake Ollama.
- **Phase 5 — CLI: `auth`, `init`, `models`, `index`, `chat` with Textual TUI.** `.balucode.yaml` parser, user-global config and credentials, WS streaming client, tool-approval prompts, session logging.
- **Phase 6 — UI bundle + docs + release.** Settings page `ui/bundle.js`, `docs/install.md` (Ollama + ROCm), `docs/cli.md`, `docs/config.md`, `scripts/release.py`, PyPI publish workflow, submit to `BaluHost-Plugin-Market/index.json`.
