# WebApp v2 — System + Stats Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a System tab (live GPU/VRAM widget + loaded-models table) and a Stats tab (live turn indicator + 7-day usage history) to the Balu Code plugin WebApp.

**Architecture:** Three new backend routes (`GET /system`, `GET /turns/current`, `GET /stats`), a new in-memory `ActiveTurnStore`, agent-loop integration to track active turns and capture Ollama final-frame metrics, server-side DB aggregation in `AuditLogger`, and two new frontend components in `bundle.js`. System tab polls at a configurable interval (default 10 s, floor 3 s).

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, httpx (MockTransport for tests), pytest-asyncio, subprocess (rocm-smi / amd-smi / nvidia-smi), plain ES-module JavaScript (no build step, `window.React`).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `plugin/config.py` | Modify | add `poll_interval_seconds` |
| `plugin/schemas.py` | Modify | add system/stats/turns schemas; extend `ConfigUpdateRequest` |
| `plugin/services/system.py` | Create | `get_gpu_info()` — subprocess wrapper, rocm/nvidia fallback |
| `plugin/services/ollama_client.py` | Modify | add `ps()` method |
| `plugin/services/active_turn.py` | Create | in-memory active turn singleton |
| `plugin/services/audit.py` | Modify | add `record_turn_end()`, `query_stats()` |
| `plugin/services/agent_loop.py` | Modify | integrate active_turn + capture Ollama final frame |
| `plugin/routes.py` | Modify | add `GET /system`, `GET /turns/current`, `GET /stats` |
| `plugin/ui/bundle.js` | Modify | add `SystemTab`, `StatsTab`; poll_interval in Config tab |
| `plugin/tests/test_system.py` | Create | tests for `get_gpu_info` |
| `plugin/tests/test_ollama_client_ps.py` | Create | tests for `OllamaClient.ps()` |
| `plugin/tests/test_active_turn.py` | Create | tests for active_turn module |
| `plugin/tests/test_audit_stats.py` | Create | tests for `record_turn_end` + `query_stats` |
| `plugin/tests/test_routes_system_stats.py` | Create | route tests for /system, /turns/current, /stats |

---

## Task 1: Config extension — `poll_interval_seconds`

**Files:**
- Modify: `plugin/config.py`
- Modify: `plugin/schemas.py`
- Modify: `plugin/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `plugin/tests/test_config.py`:

```python
def test_poll_interval_seconds_default():
    cfg = BaluCodePluginConfig()
    assert cfg.poll_interval_seconds == 10


def test_poll_interval_seconds_min_enforced():
    with pytest.raises(Exception):
        BaluCodePluginConfig(poll_interval_seconds=2)


def test_config_update_request_accepts_poll_interval():
    from plugin.schemas import ConfigUpdateRequest
    req = ConfigUpdateRequest(poll_interval_seconds=5)
    assert req.poll_interval_seconds == 5


def test_config_update_request_rejects_poll_interval_below_3():
    from plugin.schemas import ConfigUpdateRequest
    with pytest.raises(Exception):
        ConfigUpdateRequest(poll_interval_seconds=2)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sven/projects/plugins/Balu_Code
pytest plugin/tests/test_config.py -v -k "poll_interval"
```

Expected: `AttributeError` or `ValidationError`.

- [ ] **Step 3: Add `poll_interval_seconds` to `plugin/config.py`**

Add after the `temperature` field:

```python
poll_interval_seconds: int = Field(default=10, ge=3, le=300)
```

- [ ] **Step 4: Add `poll_interval_seconds` to `ConfigUpdateRequest` in `plugin/schemas.py`**

Add after the `temperature` line in `ConfigUpdateRequest`:

```python
poll_interval_seconds: int | None = Field(default=None, ge=3, le=300)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest plugin/tests/test_config.py -v -k "poll_interval"
```

Expected: 4 tests PASS.

- [ ] **Step 6: Run full suite — no regressions**

```bash
pytest plugin/tests/ -v
```

Expected: all existing tests PASS.

- [ ] **Step 7: Commit**

```bash
git add plugin/config.py plugin/schemas.py plugin/tests/test_config.py
git commit -m "feat(plugin): add poll_interval_seconds to config"
```

---

## Task 2: GPU info helper — `plugin/services/system.py`

**Files:**
- Create: `plugin/services/system.py`
- Create: `plugin/tests/test_system.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_system.py`:

```python
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from plugin.services.system import get_gpu_info


def _mock_run(stdout: str, returncode: int = 0):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    return m


# ── amd-smi ──────────────────────────────────────────────────────────────────

AMD_SMI_JSON = json.dumps([
    {
        "gpu": 0,
        "gfx": {"activity": 42},
        "mem": {"vram_used": 10_500_000_000, "vram_total": 21_474_836_480},
    }
])


def test_get_gpu_info_amd_smi():
    with patch("subprocess.run", return_value=_mock_run(AMD_SMI_JSON)):
        info = get_gpu_info()
    assert info is not None
    assert info["backend"] == "rocm"
    assert info["utilization_pct"] == 42
    assert info["vram_used_bytes"] == 10_500_000_000
    assert info["vram_total_bytes"] == 21_474_836_480
    assert info["available"] is True


# ── rocm-smi fallback ─────────────────────────────────────────────────────────

ROCM_SMI_JSON = json.dumps({
    "card0": {
        "gpu_busy_percent": "37",
        "vram": {"mem_used": 9_000_000_000, "mem_total": 21_474_836_480},
    }
})


def test_get_gpu_info_rocm_smi_fallback():
    def _side_effect(cmd, **kwargs):
        if "amd-smi" in cmd[0]:
            raise FileNotFoundError
        return _mock_run(ROCM_SMI_JSON)

    with patch("subprocess.run", side_effect=_side_effect):
        info = get_gpu_info()
    assert info is not None
    assert info["backend"] == "rocm"
    assert info["utilization_pct"] == 37


# ── nvidia-smi fallback ───────────────────────────────────────────────────────

def test_get_gpu_info_nvidia_fallback():
    def _side_effect(cmd, **kwargs):
        if cmd[0] in ("amd-smi", "rocm-smi"):
            raise FileNotFoundError
        return _mock_run("65, 8192, 24576")

    with patch("subprocess.run", side_effect=_side_effect):
        info = get_gpu_info()
    assert info is not None
    assert info["backend"] == "nvidia"
    assert info["utilization_pct"] == 65
    assert info["vram_used_bytes"] == 8192 * 1_000_000
    assert info["vram_total_bytes"] == 24576 * 1_000_000


def test_get_gpu_info_returns_none_when_no_tools():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        info = get_gpu_info()
    assert info is None


def test_get_gpu_info_returns_none_on_bad_json():
    with patch("subprocess.run", return_value=_mock_run("not json")):
        info = get_gpu_info()
    assert info is None


def test_get_gpu_info_returns_none_on_nonzero_returncode():
    with patch("subprocess.run", return_value=_mock_run("", returncode=1)):
        info = get_gpu_info()
    assert info is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest plugin/tests/test_system.py -v
```

Expected: `ImportError: cannot import name 'get_gpu_info'`.

- [ ] **Step 3: Create `plugin/services/system.py`**

```python
"""GPU hardware info via rocm-smi / amd-smi / nvidia-smi."""
from __future__ import annotations

import json
import subprocess


def _run(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=2, check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _parse_amd_smi(output: str) -> dict | None:
    try:
        data = json.loads(output)
        if not isinstance(data, list) or not data:
            return None
        gpu = data[0]
        util = (gpu.get("gfx") or {}).get("activity")
        mem = gpu.get("mem") or {}
        vram_used = mem.get("vram_used")
        vram_total = mem.get("vram_total")
        if util is None or vram_used is None or vram_total is None:
            return None
        return {
            "available": True,
            "backend": "rocm",
            "utilization_pct": int(str(util).rstrip("%")),
            "vram_used_bytes": int(vram_used),
            "vram_total_bytes": int(vram_total),
        }
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def _parse_rocm_smi(output: str) -> dict | None:
    try:
        data = json.loads(output)
        card = next(iter(data.values()), {})
        util = card.get("gpu_busy_percent")
        vram = card.get("vram") or {}
        vram_used = vram.get("mem_used")
        vram_total = vram.get("mem_total")
        if util is None or vram_used is None or vram_total is None:
            return None
        return {
            "available": True,
            "backend": "rocm",
            "utilization_pct": int(str(util).rstrip("%")),
            "vram_used_bytes": int(vram_used),
            "vram_total_bytes": int(vram_total),
        }
    except (json.JSONDecodeError, KeyError, ValueError, TypeError, StopIteration):
        return None


def _parse_nvidia_smi(output: str) -> dict | None:
    try:
        parts = [p.strip() for p in output.strip().split(",")]
        if len(parts) < 3:
            return None
        util, mem_used_mb, mem_total_mb = int(parts[0]), int(parts[1]), int(parts[2])
        return {
            "available": True,
            "backend": "nvidia",
            "utilization_pct": util,
            "vram_used_bytes": mem_used_mb * 1_000_000,
            "vram_total_bytes": mem_total_mb * 1_000_000,
        }
    except (ValueError, IndexError):
        return None


def get_gpu_info() -> dict | None:
    """Return GPU utilization + VRAM info, or None if no GPU tool is available."""
    out = _run(["amd-smi", "metric", "--json"])
    if out:
        result = _parse_amd_smi(out)
        if result:
            return result

    out = _run(["rocm-smi", "--json", "--showuse", "--showmeminfo", "vram"])
    if out:
        result = _parse_rocm_smi(out)
        if result:
            return result

    out = _run([
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ])
    if out:
        result = _parse_nvidia_smi(out)
        if result:
            return result

    return None


__all__ = ["get_gpu_info"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest plugin/tests/test_system.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/services/system.py plugin/tests/test_system.py
git commit -m "feat(plugin): add GPU info helper (rocm-smi/amd-smi/nvidia-smi)"
```

---

## Task 3: `OllamaClient.ps()`

**Files:**
- Modify: `plugin/services/ollama_client.py`
- Create: `plugin/tests/test_ollama_client_ps.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_ollama_client_ps.py`:

```python
from __future__ import annotations

import httpx
import pytest

from plugin.services.ollama_client import OllamaClient, OllamaUnreachable


def _transport(status: int, body: dict | Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_ps_returns_loaded_models():
    body = {
        "models": [
            {"name": "qwen2.5-coder:14b", "size_vram": 9_200_000_000, "context_length": 32768},
            {"name": "nomic-embed-text", "size_vram": 300_000_000, "context_length": None},
        ]
    }
    client = OllamaClient(transport=_transport(200, body))
    models = await client.ps()
    assert len(models) == 2
    assert models[0]["name"] == "qwen2.5-coder:14b"
    assert models[0]["size_vram"] == 9_200_000_000
    assert models[1]["context_length"] is None


@pytest.mark.asyncio
async def test_ps_returns_empty_list_when_no_models():
    client = OllamaClient(transport=_transport(200, {"models": []}))
    models = await client.ps()
    assert models == []


@pytest.mark.asyncio
async def test_ps_returns_empty_on_unreachable():
    client = OllamaClient(transport=_transport(500, {"error": "fail"}))
    models = await client.ps()
    assert models == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest plugin/tests/test_ollama_client_ps.py -v
```

Expected: `AttributeError: 'OllamaClient' object has no attribute 'ps'`.

- [ ] **Step 3: Add `ps()` to `plugin/services/ollama_client.py`**

Add after the `list_models` method:

```python
async def ps(self) -> list[dict]:
    """Return currently loaded models from /api/ps.

    Returns empty list if Ollama is unreachable instead of raising.
    """
    try:
        response = await self._request_with_retry("GET", "/api/ps")
    except OllamaError:
        return []
    try:
        payload: Any = response.json()
    except (json.JSONDecodeError, ValueError):
        return []
    result = []
    for entry in payload.get("models", []):
        result.append({
            "name": entry.get("name", ""),
            "size_vram": entry.get("size_vram", 0),
            "context_length": entry.get("context_length"),
        })
    return result
```

Also add `"ps"` export — update `__all__` at the bottom of `ollama_client.py`:

```python
__all__ = [
    "OllamaClient",
    "OllamaError",
    "OllamaModel",
    "OllamaRateLimited",
    "OllamaTimeoutError",
    "OllamaUnreachable",
]
```

(`ps` is a method, not a standalone symbol — no change to `__all__` needed.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest plugin/tests/test_ollama_client_ps.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/services/ollama_client.py plugin/tests/test_ollama_client_ps.py
git commit -m "feat(plugin): add OllamaClient.ps() for loaded-model VRAM info"
```

---

## Task 4: `GET /system` — schemas + route + tests

**Files:**
- Modify: `plugin/schemas.py`
- Modify: `plugin/routes.py`
- Create: `plugin/tests/test_routes_system_stats.py`

- [ ] **Step 1: Add system schemas to `plugin/schemas.py`**

Add after `LogsResponse`:

```python
class LoadedModel(BaseModel):
    name: str
    size_vram: int
    context_length: int | None = None


class OllamaSystemInfo(BaseModel):
    reachable: bool
    loaded_models: list[LoadedModel] = []


class GpuInfo(BaseModel):
    available: bool
    backend: str | None = None
    utilization_pct: int | None = None
    vram_used_bytes: int | None = None
    vram_total_bytes: int | None = None


class SystemResponse(BaseModel):
    ollama: OllamaSystemInfo
    gpu: GpuInfo
```

Also add `"GpuInfo"`, `"LoadedModel"`, `"OllamaSystemInfo"`, `"SystemResponse"` to `__all__`.

- [ ] **Step 2: Write the failing tests**

Create `plugin/tests/test_routes_system_stats.py`:

```python
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin import BaluCodePlugin
from plugin.config import BaluCodePluginConfig
from plugin.deps import get_audit_log, get_data_dir, get_ollama_client, get_plugin_config


class _FakeOllama:
    async def list_models(self):
        return []

    async def ps(self):
        return [{"name": "qwen2.5-coder:14b", "size_vram": 9_000_000_000, "context_length": 32768}]


class _FakeAuditLog:
    async def record_tool_call(self, **kwargs) -> None:
        pass

    async def query_recent_tool_calls(self, limit: int = 100) -> list[dict]:
        return []

    async def record_turn_end(self, **kwargs) -> None:
        pass

    async def query_stats(self, days: int = 7) -> dict:
        return {
            "last_n_days": [
                {"date": "2026-04-26", "requests": 5, "tokens_in": 10000, "tokens_out": 2000}
            ],
            "by_model": [
                {"model": "qwen2.5-coder:14b", "requests": 5, "avg_tokens_per_s": 18.5}
            ],
            "top_tools": [
                {"tool": "read_file", "calls": 20, "success_rate": 0.95}
            ],
            "approval_summary": {"auto_approved": 15, "user_approved": 3, "rejected": 1},
        }


_GPU_INFO = {
    "available": True,
    "backend": "rocm",
    "utilization_pct": 42,
    "vram_used_bytes": 9_500_000_000,
    "vram_total_bytes": 21_474_836_480,
}


def _make_app(tmp_path):
    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_plugin_config] = lambda: BaluCodePluginConfig()
    app.dependency_overrides[get_data_dir] = lambda: tmp_path
    app.dependency_overrides[get_ollama_client] = lambda: _FakeOllama()
    app.dependency_overrides[get_audit_log] = lambda: _FakeAuditLog()
    return app


# ── /system ───────────────────────────────────────────────────────────────────

def test_get_system_with_gpu(tmp_path):
    client = TestClient(_make_app(tmp_path))
    with patch("plugin.routes.get_gpu_info", return_value=_GPU_INFO):
        r = client.get("/api/plugins/balu_code/system")
    assert r.status_code == 200
    body = r.json()
    assert body["ollama"]["reachable"] is True
    assert body["ollama"]["loaded_models"][0]["name"] == "qwen2.5-coder:14b"
    assert body["gpu"]["available"] is True
    assert body["gpu"]["utilization_pct"] == 42


def test_get_system_gpu_unavailable(tmp_path):
    client = TestClient(_make_app(tmp_path))
    with patch("plugin.routes.get_gpu_info", return_value=None):
        r = client.get("/api/plugins/balu_code/system")
    assert r.status_code == 200
    assert r.json()["gpu"]["available"] is False
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest plugin/tests/test_routes_system_stats.py::test_get_system_with_gpu -v
```

Expected: FAIL — route not defined yet.

- [ ] **Step 4: Add `GET /system` to `plugin/routes.py`**

Add to the top-level imports block:

```python
from .schemas import (
    ...
    GpuInfo,
    LoadedModel,
    OllamaSystemInfo,
    SystemResponse,
)
from .services.system import get_gpu_info
```

Add the route inside `build_router()`, after the logs route:

```python
    @router.get("/system", response_model=SystemResponse, tags=["balu_code"])
    async def get_system_route(
        _user: UserPublic = Depends(get_current_user),
        ollama: OllamaClient = Depends(get_ollama_client),
    ) -> SystemResponse:
        loaded_raw, gpu_raw = await asyncio.gather(
            ollama.ps(),
            asyncio.to_thread(get_gpu_info),
        )
        loaded = [LoadedModel(**m) for m in loaded_raw]
        ollama_info = OllamaSystemInfo(reachable=True, loaded_models=loaded)
        if gpu_raw is None:
            gpu_info = GpuInfo(available=False)
        else:
            gpu_info = GpuInfo(**gpu_raw)
        return SystemResponse(ollama=ollama_info, gpu=gpu_info)
```

- [ ] **Step 5: Run system tests**

```bash
pytest plugin/tests/test_routes_system_stats.py -k "system" -v
```

Expected: 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/schemas.py plugin/routes.py plugin/tests/test_routes_system_stats.py
git commit -m "feat(plugin): add GET /system route with GPU + Ollama ps info"
```

---

## Task 5: `plugin/services/active_turn.py`

**Files:**
- Create: `plugin/services/active_turn.py`
- Create: `plugin/tests/test_active_turn.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_active_turn.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import plugin.services.active_turn as at
from plugin.services.active_turn import (
    ActiveTurn,
    clear_active,
    get_active,
    set_active,
    update_iterations,
)


@pytest.fixture(autouse=True)
def _reset():
    at._active = None
    yield
    at._active = None


def _turn(turn_id: str = "t_abc") -> ActiveTurn:
    return ActiveTurn(
        turn_id=turn_id,
        model="qwen2.5-coder:14b",
        started_at=datetime.now(timezone.utc),
        iterations=0,
        username="sven",
    )


def test_get_active_returns_none_initially():
    assert get_active() is None


def test_set_then_get_returns_turn():
    t = _turn()
    set_active(t)
    assert get_active() is t


def test_clear_active_removes_turn():
    set_active(_turn("t1"))
    clear_active("t1")
    assert get_active() is None


def test_clear_wrong_turn_id_is_noop():
    t = _turn("t1")
    set_active(t)
    clear_active("t_other")
    assert get_active() is t


def test_update_iterations_increments_count():
    t = _turn("t1")
    set_active(t)
    update_iterations("t1", 3)
    assert get_active().iterations == 3


def test_update_iterations_wrong_turn_id_is_noop():
    t = _turn("t1")
    set_active(t)
    update_iterations("t_other", 99)
    assert get_active().iterations == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest plugin/tests/test_active_turn.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `plugin/services/active_turn.py`**

```python
"""In-memory singleton tracking the currently running agent turn."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ActiveTurn:
    turn_id: str
    model: str
    started_at: datetime
    iterations: int
    username: str


_active: ActiveTurn | None = None


def set_active(turn: ActiveTurn) -> None:
    global _active
    _active = turn


def update_iterations(turn_id: str, count: int) -> None:
    global _active
    if _active is not None and _active.turn_id == turn_id:
        _active.iterations = count


def clear_active(turn_id: str) -> None:
    global _active
    if _active is not None and _active.turn_id == turn_id:
        _active = None


def get_active() -> ActiveTurn | None:
    return _active


__all__ = ["ActiveTurn", "clear_active", "get_active", "set_active", "update_iterations"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest plugin/tests/test_active_turn.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/services/active_turn.py plugin/tests/test_active_turn.py
git commit -m "feat(plugin): add active_turn in-memory singleton"
```

---

## Task 6: `GET /turns/current` — schema + route + tests

**Files:**
- Modify: `plugin/schemas.py`
- Modify: `plugin/routes.py`
- Modify: `plugin/tests/test_routes_system_stats.py`

- [ ] **Step 1: Add `TurnCurrentResponse` to `plugin/schemas.py`**

Add after `SystemResponse`:

```python
class TurnCurrentResponse(BaseModel):
    active: bool
    turn_id: str | None = None
    model: str | None = None
    started_at: str | None = None
    elapsed_seconds: int | None = None
    iterations: int | None = None
    username: str | None = None
```

Add `"TurnCurrentResponse"` to `__all__`.

- [ ] **Step 2: Write the failing tests**

Add to `plugin/tests/test_routes_system_stats.py`:

```python
# ── /turns/current ────────────────────────────────────────────────────────────

def test_turns_current_idle(tmp_path):
    import plugin.services.active_turn as at
    at._active = None
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/turns/current")
    assert r.status_code == 200
    assert r.json()["active"] is False


def test_turns_current_active(tmp_path):
    from datetime import datetime, timezone
    from plugin.services.active_turn import ActiveTurn, set_active
    import plugin.services.active_turn as at
    at._active = None
    set_active(ActiveTurn(
        turn_id="t_test",
        model="qwen2.5-coder:14b",
        started_at=datetime.now(timezone.utc),
        iterations=3,
        username="sven",
    ))
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/turns/current")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True
    assert body["turn_id"] == "t_test"
    assert body["iterations"] == 3
    assert body["model"] == "qwen2.5-coder:14b"
    assert body["elapsed_seconds"] is not None
    at._active = None
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest plugin/tests/test_routes_system_stats.py -k "turns_current" -v
```

Expected: FAIL — route not defined yet.

- [ ] **Step 4: Add `GET /turns/current` to `plugin/routes.py`**

Add to imports block:

```python
from .schemas import (
    ...
    TurnCurrentResponse,
)
```

Add the route inside `build_router()`, after the system route:

```python
    @router.get("/turns/current", response_model=TurnCurrentResponse, tags=["balu_code"])
    async def get_turns_current(
        _user: UserPublic = Depends(get_current_user),
    ) -> TurnCurrentResponse:
        from datetime import datetime, timezone
        from .services.active_turn import get_active
        turn = get_active()
        if turn is None:
            return TurnCurrentResponse(active=False)
        elapsed = int((datetime.now(timezone.utc) - turn.started_at).total_seconds())
        return TurnCurrentResponse(
            active=True,
            turn_id=turn.turn_id,
            model=turn.model,
            started_at=turn.started_at.isoformat(),
            elapsed_seconds=elapsed,
            iterations=turn.iterations,
            username=turn.username,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest plugin/tests/test_routes_system_stats.py -k "turns_current" -v
```

Expected: 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/schemas.py plugin/routes.py plugin/tests/test_routes_system_stats.py
git commit -m "feat(plugin): add GET /turns/current endpoint"
```

---

## Task 7: Agent-loop integration — active_turn + final-frame capture

**Files:**
- Modify: `plugin/services/agent_loop.py`

This task wires `active_turn` into `run_turn` and captures the Ollama final frame for metrics. No new public API — changes are internal. The `record_turn_end` call is added in Task 8.

- [ ] **Step 1: Add imports to `agent_loop.py`**

Add after the existing imports (after `from .tools.base import ToolContext`):

```python
from datetime import datetime, timezone
from .active_turn import ActiveTurn, clear_active, set_active, update_iterations
```

- [ ] **Step 2: Add `_final_frame` tracking and `set_active` call**

In `run_turn`, after the line `await emit(TurnStart(...))` and before `total_tokens = assembled.context_tokens`, add:

```python
    set_active(ActiveTurn(
        turn_id=turn_id,
        model=deps.config.chat_model,
        started_at=datetime.now(timezone.utc),
        iterations=0,
        username=ctx.username,
    ))
    _final_frame: dict = {}
```

- [ ] **Step 3: Add `update_iterations` call at top of each iteration**

Inside the `for _iteration in range(deps.config.max_iterations):` loop, add immediately after `iterations += 1`:

```python
        update_iterations(turn_id, iterations)
```

- [ ] **Step 4: Capture the Ollama final frame**

In the streaming loop, change:

```python
                if frame.get("done"):
                    _log.warning(
                        "[agent_loop] stream done — buffered=%d bytes",
                        len(buffered_content),
                    )
                    break
```

To:

```python
                if frame.get("done"):
                    _final_frame = frame
                    _log.warning(
                        "[agent_loop] stream done — buffered=%d bytes",
                        len(buffered_content),
                    )
                    break
```

- [ ] **Step 5: Wrap the for-loop + final TurnEnd in try/finally**

The `for` loop and the `await emit(TurnEnd(..., stop_reason="max_iter"))` after it must be wrapped. The full structure after your edits should be:

```python
    total_tokens = assembled.context_tokens
    iterations = 0
    try:
        for _iteration in range(deps.config.max_iterations):
            iterations += 1
            update_iterations(turn_id, iterations)
            # ... (rest of existing loop body, unchanged) ...

        await emit(
            TurnEnd(
                turn_id=turn_id,
                total_tokens=total_tokens,
                iterations=iterations,
                stop_reason="max_iter",
            )
        )
    finally:
        clear_active(turn_id)
```

**Important:** The `record_turn_end` call goes in the `finally` block too, but only in Task 8 after `AuditLogger.record_turn_end` exists. For now, just `clear_active(turn_id)` in the finally.

- [ ] **Step 6: Run the full test suite — no regressions**

```bash
pytest plugin/tests/ -v
```

Expected: all existing tests PASS.

- [ ] **Step 7: Commit**

```bash
git add plugin/services/agent_loop.py
git commit -m "feat(agent): track active turn + capture Ollama final frame"
```

---

## Task 8: `AuditLogger.record_turn_end()` + `query_stats()` + agent-loop call

**Files:**
- Modify: `plugin/services/audit.py`
- Create: `plugin/tests/test_audit_stats.py`
- Modify: `plugin/services/agent_loop.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_audit_stats.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from plugin.services.audit import AuditLogger


class _FakeDBLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def log_event(self, *, event_type, user, action, resource=None,
                  details=None, success=True, error_message=None, **kw):
        self.calls.append({
            "event_type": event_type, "user": user, "action": action,
            "resource": resource, "details": details,
            "success": success, "error_message": error_message,
        })


@pytest.mark.asyncio
async def test_record_turn_end_logs_turn_end_action():
    db = _FakeDBLogger()
    audit = AuditLogger(db)
    await audit.record_turn_end(
        turn_id="t1",
        model="qwen2.5-coder:14b",
        username="sven",
        prompt_eval_count=1000,
        eval_count=400,
        eval_duration_ns=22_000_000_000,
        total_duration_ms=25000,
        iterations=3,
    )
    assert len(db.calls) == 1
    call = db.calls[0]
    assert call["action"] == "turn:end"
    assert call["resource"] == "qwen2.5-coder:14b"
    assert call["user"] == "sven"
    details = call["details"]
    assert details["turn_id"] == "t1"
    assert details["eval_count"] == 400
    assert details["prompt_eval_count"] == 1000
    assert details["iterations"] == 3
    assert details["tokens_per_s"] > 0


@pytest.mark.asyncio
async def test_record_turn_end_zero_duration_does_not_divide_by_zero():
    db = _FakeDBLogger()
    audit = AuditLogger(db)
    await audit.record_turn_end(
        turn_id="t2",
        model="qwen2.5-coder:14b",
        username="sven",
        prompt_eval_count=0,
        eval_count=0,
        eval_duration_ns=0,
        total_duration_ms=0,
        iterations=1,
    )
    details = db.calls[0]["details"]
    assert details["tokens_per_s"] == 0.0


@pytest.mark.asyncio
async def test_query_stats_returns_expected_shape():
    db = _FakeDBLogger()
    audit = AuditLogger(db)
    with patch.object(audit, "_query_stats_sync", return_value={
        "last_n_days": [{"date": "2026-04-26", "requests": 5,
                         "tokens_in": 10000, "tokens_out": 2000}],
        "by_model": [{"model": "qwen2.5-coder:14b", "requests": 5, "avg_tokens_per_s": 18.5}],
        "top_tools": [{"tool": "read_file", "calls": 20, "success_rate": 0.95}],
        "approval_summary": {"auto_approved": 15, "user_approved": 3, "rejected": 1},
    }):
        result = await audit.query_stats(days=7)
    assert "last_n_days" in result
    assert "by_model" in result
    assert "top_tools" in result
    assert "approval_summary" in result
    assert result["approval_summary"]["auto_approved"] == 15
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest plugin/tests/test_audit_stats.py -v
```

Expected: `AttributeError: 'AuditLogger' object has no attribute 'record_turn_end'`.

- [ ] **Step 3: Add `record_turn_end` and `query_stats` to `plugin/services/audit.py`**

Add after the `query_recent_tool_calls` method:

```python
    async def record_turn_end(
        self,
        *,
        turn_id: str,
        model: str,
        username: str,
        prompt_eval_count: int,
        eval_count: int,
        eval_duration_ns: int,
        total_duration_ms: int,
        iterations: int,
    ) -> None:
        tokens_per_s = (
            round(eval_count / (eval_duration_ns / 1e9), 2)
            if eval_duration_ns > 0
            else 0.0
        )
        details = {
            "turn_id": turn_id,
            "model": model,
            "prompt_eval_count": prompt_eval_count,
            "eval_count": eval_count,
            "tokens_per_s": tokens_per_s,
            "total_duration_ms": total_duration_ms,
            "iterations": iterations,
        }
        await asyncio.to_thread(
            self._db.log_event,
            event_type=_EVENT_TYPE,
            user=username,
            action="turn:end",
            resource=model,
            details=details,
            success=True,
            error_message=None,
        )

    async def query_stats(self, days: int = 7) -> dict:
        return await asyncio.to_thread(self._query_stats_sync, days)

    def _query_stats_sync(self, days: int) -> dict:
        import json as _json
        from datetime import datetime, timedelta, timezone

        from app.core.database import SessionLocal
        from app.models.audit_log import AuditLog as DBLog

        since = datetime.now(timezone.utc) - timedelta(days=days)

        with SessionLocal() as db:
            if db is None:
                return _empty_stats(days)

            turn_rows = (
                db.query(DBLog)
                .filter(DBLog.event_type == "BALU_CODE", DBLog.action == "turn:end")
                .filter(DBLog.timestamp >= since)
                .order_by(DBLog.timestamp.asc())
                .all()
            )
            tool_rows = (
                db.query(DBLog)
                .filter(DBLog.event_type == "BALU_CODE", DBLog.action.like("tool:%"))
                .filter(DBLog.timestamp >= since)
                .all()
            )

        days_map: dict[str, dict] = {}
        for i in range(days):
            d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
            days_map[d] = {"date": d, "requests": 0, "tokens_in": 0, "tokens_out": 0}

        by_model: dict[str, dict] = {}
        for row in turn_rows:
            det = _json.loads(row.details) if row.details else {}
            d = row.timestamp.strftime("%Y-%m-%d")
            if d in days_map:
                days_map[d]["requests"] += 1
                days_map[d]["tokens_in"] += det.get("prompt_eval_count", 0)
                days_map[d]["tokens_out"] += det.get("eval_count", 0)
            m = det.get("model", "unknown")
            if m not in by_model:
                by_model[m] = {"model": m, "requests": 0, "_tps_sum": 0.0}
            by_model[m]["requests"] += 1
            by_model[m]["_tps_sum"] += det.get("tokens_per_s", 0.0)

        by_model_list = [
            {
                "model": v["model"],
                "requests": v["requests"],
                "avg_tokens_per_s": round(v["_tps_sum"] / v["requests"], 2)
                if v["requests"] > 0 else 0.0,
            }
            for v in by_model.values()
        ]

        tool_counts: dict[str, dict] = {}
        auto_approved = user_approved = rejected = 0
        for row in tool_rows:
            det = _json.loads(row.details) if row.details else {}
            name = row.action.removeprefix("tool:")
            if name not in tool_counts:
                tool_counts[name] = {"tool": name, "calls": 0, "_ok": 0}
            tool_counts[name]["calls"] += 1
            if row.success:
                tool_counts[name]["_ok"] += 1
            if det.get("auto_approved"):
                auto_approved += 1
            elif det.get("approved"):
                user_approved += 1
            else:
                rejected += 1

        top_tools = sorted(
            [
                {
                    "tool": v["tool"],
                    "calls": v["calls"],
                    "success_rate": round(v["_ok"] / v["calls"], 2)
                    if v["calls"] > 0 else 0.0,
                }
                for v in tool_counts.values()
            ],
            key=lambda x: x["calls"],
            reverse=True,
        )[:10]

        return {
            "last_n_days": list(days_map.values()),
            "by_model": by_model_list,
            "top_tools": top_tools,
            "approval_summary": {
                "auto_approved": auto_approved,
                "user_approved": user_approved,
                "rejected": rejected,
            },
        }
```

Also add this module-level helper after the `AuditLogger` class (outside the class):

```python
def _empty_stats(days: int) -> dict:
    from datetime import datetime, timedelta, timezone
    return {
        "last_n_days": [
            {
                "date": (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d"),
                "requests": 0, "tokens_in": 0, "tokens_out": 0,
            }
            for i in range(days)
        ],
        "by_model": [],
        "top_tools": [],
        "approval_summary": {"auto_approved": 0, "user_approved": 0, "rejected": 0},
    }
```

Update `__all__` to include `"_empty_stats"` — actually it's private, leave `__all__` as is.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest plugin/tests/test_audit_stats.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Add `record_turn_end` call to `agent_loop.py` `finally` block**

In `plugin/services/agent_loop.py`, update the `finally` block (added in Task 7) from:

```python
    finally:
        clear_active(turn_id)
```

To:

```python
    finally:
        clear_active(turn_id)
        try:
            await deps.audit_log.record_turn_end(
                turn_id=turn_id,
                model=deps.config.chat_model,
                username=ctx.username,
                prompt_eval_count=_final_frame.get("prompt_eval_count", 0),
                eval_count=_final_frame.get("eval_count", 0),
                eval_duration_ns=_final_frame.get("eval_duration", 0),
                total_duration_ms=(
                    (_final_frame.get("total_duration") or 0) // 1_000_000
                ),
                iterations=iterations,
            )
        except Exception:
            pass
```

- [ ] **Step 6: Run the full test suite**

```bash
pytest plugin/tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add plugin/services/audit.py plugin/tests/test_audit_stats.py plugin/services/agent_loop.py
git commit -m "feat(plugin): add record_turn_end + query_stats to AuditLogger"
```

---

## Task 9: `GET /stats` — schemas + route + tests

**Files:**
- Modify: `plugin/schemas.py`
- Modify: `plugin/routes.py`
- Modify: `plugin/tests/test_routes_system_stats.py`

- [ ] **Step 1: Add stats schemas to `plugin/schemas.py`**

Add after `TurnCurrentResponse`:

```python
class DayStat(BaseModel):
    date: str
    requests: int
    tokens_in: int
    tokens_out: int


class ModelStat(BaseModel):
    model: str
    requests: int
    avg_tokens_per_s: float


class ToolStat(BaseModel):
    tool: str
    calls: int
    success_rate: float


class ApprovalSummary(BaseModel):
    auto_approved: int
    user_approved: int
    rejected: int


class StatsResponse(BaseModel):
    last_n_days: list[DayStat]
    by_model: list[ModelStat]
    top_tools: list[ToolStat]
    approval_summary: ApprovalSummary
```

Add all five names to `__all__`.

- [ ] **Step 2: Write the failing tests**

Add to `plugin/tests/test_routes_system_stats.py`:

```python
# ── /stats ────────────────────────────────────────────────────────────────────

def test_get_stats_returns_expected_shape(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/stats")
    assert r.status_code == 200
    body = r.json()
    assert "last_n_days" in body
    assert "by_model" in body
    assert "top_tools" in body
    assert "approval_summary" in body
    assert body["approval_summary"]["auto_approved"] == 15


def test_get_stats_custom_days(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/stats?days=14")
    assert r.status_code == 200


def test_get_stats_rejects_excessive_days(tmp_path):
    client = TestClient(_make_app(tmp_path))
    r = client.get("/api/plugins/balu_code/stats?days=91")
    assert r.status_code == 422
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest plugin/tests/test_routes_system_stats.py -k "stats" -v
```

Expected: FAIL — route not defined yet.

- [ ] **Step 4: Add `GET /stats` to `plugin/routes.py`**

Add to imports:

```python
from .schemas import (
    ...
    ApprovalSummary,
    DayStat,
    ModelStat,
    StatsResponse,
    ToolStat,
)
```

Add the route inside `build_router()`, after the turns/current route:

```python
    @router.get("/stats", response_model=StatsResponse, tags=["balu_code"])
    async def get_stats_route(
        days: int = Query(default=7, ge=1, le=90),
        _user: UserPublic = Depends(get_current_user),
        audit_log=Depends(get_audit_log),
    ) -> StatsResponse:
        raw = await audit_log.query_stats(days=days)
        return StatsResponse(
            last_n_days=[DayStat(**d) for d in raw["last_n_days"]],
            by_model=[ModelStat(**m) for m in raw["by_model"]],
            top_tools=[ToolStat(**t) for t in raw["top_tools"]],
            approval_summary=ApprovalSummary(**raw["approval_summary"]),
        )
```

- [ ] **Step 5: Run all routes tests**

```bash
pytest plugin/tests/test_routes_system_stats.py -v
```

Expected: all 9 tests in the file PASS.

- [ ] **Step 6: Run full suite**

```bash
pytest plugin/tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add plugin/schemas.py plugin/routes.py plugin/tests/test_routes_system_stats.py
git commit -m "feat(plugin): add GET /stats endpoint with 7-day usage aggregation"
```

---

## Task 10: Frontend — poll_interval in Config + SystemTab

**Files:**
- Modify: `plugin/ui/bundle.js`

- [ ] **Step 1: Add `poll_interval_seconds` to `CONFIG_FIELDS`**

In `bundle.js`, find the `CONFIG_FIELDS` array. Add as the last entry:

```javascript
  { key: 'poll_interval_seconds', label: 'System poll interval (s, min 3)', type: 'number' },
```

- [ ] **Step 2: Add `SystemTab` component**

Add the following before `const TABS = [...]`:

```javascript
// ── System tab ────────────────────────────────────────────────────────────────

function useInterval(callback, delayMs) {
  const savedCallback = React.useRef(callback);
  React.useEffect(() => { savedCallback.current = callback; }, [callback]);
  React.useEffect(() => {
    if (delayMs == null) return;
    const id = setInterval(() => savedCallback.current(), delayMs);
    return () => clearInterval(id);
  }, [delayMs]);
}

function VramBar({ usedBytes, totalBytes }) {
  if (!totalBytes) {
    const gb = usedBytes ? (usedBytes / 1e9).toFixed(1) : '—';
    return ce('span', { className: 'text-sm text-slate-400' }, `${gb} GB loaded (total unknown)`);
  }
  const pct = Math.min(100, Math.round((usedBytes / totalBytes) * 100));
  const usedGb = (usedBytes / 1e9).toFixed(1);
  const totalGb = (totalBytes / 1e9).toFixed(1);
  const color = pct > 90 ? 'bg-red-500' : pct > 70 ? 'bg-amber-500' : 'bg-sky-500';
  return ce('div', { className: 'space-y-1' },
    ce('div', { className: 'flex justify-between text-xs text-slate-400' },
      ce('span', null, `${usedGb} GB / ${totalGb} GB`),
      ce('span', null, `${pct}%`)
    ),
    ce('div', { className: 'w-full bg-slate-700 rounded-full h-2' },
      ce('div', { className: `${color} h-2 rounded-full transition-all`, style: { width: `${pct}%` } })
    )
  );
}

function SystemTab() {
  const [data, setData] = useState(null);
  const [config, setConfig] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [pollMs, setPollMs] = useState(10_000);

  useEffect(() => {
    api('/config').then(c => {
      setConfig(c);
      const interval = Math.max(3, c.poll_interval_seconds || 10) * 1000;
      setPollMs(interval);
    }).catch(() => {});
  }, []);

  const load = useCallback(() => {
    api('/system')
      .then(d => { setData(d); setLastUpdated(new Date()); setError(null); })
      .catch(e => setError(e.message));
  }, []);

  useEffect(() => { load(); }, [load]);
  useInterval(load, pollMs);

  async function changePollInterval(seconds) {
    const clamped = Math.max(3, seconds);
    setPollMs(clamped * 1000);
    try { await api('/config', { method: 'PUT', body: JSON.stringify({ poll_interval_seconds: clamped }) }); }
    catch (e) { /* non-critical */ }
  }

  const secsAgo = lastUpdated ? Math.round((Date.now() - lastUpdated) / 1000) : null;

  if (error && !data) return ce(ErrorBox, { msg: error });
  if (!data) return ce(Spinner);

  const loaded = data.ollama.loaded_models || [];
  const gpu = data.gpu;

  return ce('div', { className: 'space-y-4' },
    ce(ErrorBox, { msg: error }),

    // VRAM + GPU
    ce(Card, null,
      ce('div', { className: 'flex items-center justify-between mb-4' },
        ce('h3', { className: 'text-white font-medium' }, 'VRAM'),
        gpu.available
          ? ce(Badge, { text: `GPU ${gpu.utilization_pct}%`, ok: gpu.utilization_pct < 90 })
          : ce('span', { className: 'text-xs text-slate-500' }, 'no GPU tool')
      ),
      ce(VramBar, {
        usedBytes: loaded.reduce((s, m) => s + (m.size_vram || 0), 0),
        totalBytes: gpu.available ? gpu.vram_total_bytes : null,
      })
    ),

    // Loaded models
    ce(Card, null,
      ce('h3', { className: 'text-white font-medium mb-4' }, 'Loaded Models'),
      loaded.length === 0
        ? ce('p', { className: 'text-slate-500 text-sm' }, 'No models loaded.')
        : ce('div', { className: 'space-y-2' },
            loaded.map(m =>
              ce('div', { key: m.name, className: 'flex items-center justify-between' },
                ce('div', null,
                  ce('div', { className: 'text-white text-sm' }, m.name),
                  ce('div', { className: 'text-xs text-slate-500' },
                    `${(m.size_vram / 1e9).toFixed(1)} GB VRAM` +
                    (m.context_length ? ` · ${m.context_length.toLocaleString()} ctx` : '')
                  )
                ),
                ce('div', { className: 'flex gap-1' },
                  config?.chat_model === m.name  ? ce(Badge, { text: 'chat',  ok: true }) : null,
                  config?.embed_model === m.name ? ce(Badge, { text: 'embed', ok: true }) : null
                )
              )
            )
          )
    ),

    // Polling indicator
    ce('div', { className: 'flex items-center gap-3 text-xs text-slate-500' },
      secsAgo !== null ? ce('span', null, `Updated ${secsAgo}s ago`) : null,
      ce('span', null, '·'),
      ce('label', null, 'every'),
      ce('select', {
        value: pollMs / 1000,
        onChange: e => changePollInterval(Number(e.target.value)),
        className: 'bg-slate-800 border border-slate-700 text-slate-300 text-xs rounded px-1 py-0.5',
      },
        [3, 5, 10, 30].map(s => ce('option', { key: s, value: s }, `${s}s`))
      )
    )
  );
}
```

- [ ] **Step 3: Add `'system'` tab to `TABS`**

Change `TABS` to:

```javascript
const TABS = [
  { id: 'models',   label: 'Models' },
  { id: 'projects', label: 'Projects' },
  { id: 'config',   label: 'Config' },
  { id: 'logs',     label: 'Logs' },
  { id: 'system',   label: 'System' },
  { id: 'stats',    label: 'Stats' },
];
```

- [ ] **Step 4: Add `system` entry to the `content` map in `BaluCode`**

Change the content object inside `BaluCode`:

```javascript
  const content = {
    models:   ce(ModelsTab),
    projects: ce(ProjectsTab),
    config:   ce(ConfigTab),
    logs:     ce(LogsTab),
    system:   ce(SystemTab),
    stats:    ce('div', { className: 'text-slate-400 text-sm' }, 'Stats tab — coming in next step'),
  };
```

- [ ] **Step 5: Build check**

```bash
cd /home/sven/projects/plugins/Balu_Code
python -m scripts.build_bhplugin --repo-root . --dist dist/
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add plugin/ui/bundle.js
git commit -m "feat(ui): add SystemTab with VRAM bar + loaded models + poll interval"
```

---

## Task 11: Frontend — StatsTab

**Files:**
- Modify: `plugin/ui/bundle.js`

- [ ] **Step 1: Add `StatsTab` component**

Add the following before `const TABS`:

```javascript
// ── Stats tab ─────────────────────────────────────────────────────────────────

function TurnBanner() {
  const [turn, setTurn] = useState(null);

  const load = useCallback(() => {
    api('/turns/current').then(setTurn).catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);
  useInterval(load, 5_000);

  if (!turn) return null;
  if (!turn.active) {
    return ce('div', { className: 'text-xs text-slate-500 italic' }, 'No active turn');
  }

  function pad(n) { return String(n).padStart(2, '0'); }
  const s = turn.elapsed_seconds || 0;
  const elapsed = `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;

  return ce('div', {
    className: 'flex items-center gap-3 px-4 py-2 rounded-lg bg-sky-500/10 border border-sky-500/30 text-sm',
  },
    ce('span', { className: 'w-2 h-2 rounded-full bg-sky-400 animate-pulse' }),
    ce('span', { className: 'text-sky-300 font-medium' }, turn.model),
    ce('span', { className: 'text-slate-400' }, `${turn.iterations} iteration${turn.iterations !== 1 ? 's' : ''}`),
    ce('span', { className: 'text-slate-400' }, elapsed),
    ce('span', { className: 'text-slate-500' }, turn.username)
  );
}

function StatsTab() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(7);

  const load = useCallback(() => {
    api(`/stats?days=${days}`)
      .then(setStats)
      .catch(e => setError(e.message));
  }, [days]);

  useEffect(() => { load(); }, [load]);

  if (error && !stats) return ce(ErrorBox, { msg: error });

  const thCls = 'text-left text-slate-500 text-xs font-medium py-2 pr-4';
  const tdCls = 'py-2 pr-4 text-sm';

  function Table({ headers, rows }) {
    return ce('div', { className: 'overflow-x-auto' },
      ce('table', { className: 'w-full' },
        ce('thead', null,
          ce('tr', { className: 'border-b border-slate-800' },
            headers.map(h => ce('th', { key: h, className: thCls }, h))
          )
        ),
        ce('tbody', null,
          rows.map((row, i) =>
            ce('tr', { key: i, className: 'border-b border-slate-800/50' },
              row.map((cell, j) => ce('td', { key: j, className: `${tdCls} text-slate-300` }, cell))
            )
          )
        )
      )
    );
  }

  return ce('div', { className: 'space-y-6' },
    ce(ErrorBox, { msg: error }),
    ce(TurnBanner),

    // Header controls
    ce('div', { className: 'flex items-center justify-between' },
      ce('h2', { className: 'text-lg font-semibold text-white' }, 'Usage Stats'),
      ce('div', { className: 'flex items-center gap-2' },
        ce('label', { className: 'text-sm text-slate-400' }, 'Days'),
        ce('select', {
          value: days,
          onChange: e => setDays(Number(e.target.value)),
          className: 'bg-slate-800 border border-slate-700 text-white text-sm rounded-lg px-2 py-1',
        },
          [7, 14, 30, 90].map(n => ce('option', { key: n, value: n }, n))
        ),
        ce(Btn, { onClick: load, variant: 'ghost' }, 'Refresh')
      )
    ),

    !stats ? ce(Spinner) : ce('div', { className: 'space-y-6' },

      // Last N days
      ce(Card, null,
        ce('h3', { className: 'text-white font-medium mb-3' }, `Last ${days} days`),
        ce(Table, {
          headers: ['Date', 'Requests', 'Tokens In', 'Tokens Out'],
          rows: stats.last_n_days.map(d => [
            d.date,
            d.requests,
            d.tokens_in.toLocaleString(),
            d.tokens_out.toLocaleString(),
          ]),
        })
      ),

      // By model
      stats.by_model.length > 0 && ce(Card, null,
        ce('h3', { className: 'text-white font-medium mb-3' }, 'By Model'),
        ce(Table, {
          headers: ['Model', 'Requests', 'Avg Tokens/s'],
          rows: stats.by_model.map(m => [m.model, m.requests, m.avg_tokens_per_s]),
        })
      ),

      // Top tools
      stats.top_tools.length > 0 && ce(Card, null,
        ce('h3', { className: 'text-white font-medium mb-3' }, 'Top Tools'),
        ce(Table, {
          headers: ['Tool', 'Calls', 'Success Rate'],
          rows: stats.top_tools.map(t => [
            t.tool,
            t.calls,
            `${(t.success_rate * 100).toFixed(0)}%`,
          ]),
        })
      ),

      // Approval summary
      ce(Card, null,
        ce('h3', { className: 'text-white font-medium mb-3' }, 'Tool Approvals'),
        ce('div', { className: 'flex gap-3' },
          ce(Badge, { text: `auto: ${stats.approval_summary.auto_approved}`, ok: true }),
          ce(Badge, { text: `user: ${stats.approval_summary.user_approved}`, ok: true }),
          ce(Badge, { text: `rejected: ${stats.approval_summary.rejected}`, ok: false }),
        )
      )
    )
  );
}
```

- [ ] **Step 2: Replace the Stats placeholder in `BaluCode`**

Change:

```javascript
    stats:    ce('div', { className: 'text-slate-400 text-sm' }, 'Stats tab — coming in next step'),
```

To:

```javascript
    stats:    ce(StatsTab),
```

- [ ] **Step 3: Build check**

```bash
python -m scripts.build_bhplugin --repo-root . --dist dist/
```

Expected: no errors.

- [ ] **Step 4: Run full test suite + ruff**

```bash
pytest plugin/tests/ -v && ruff check plugin/ && ruff format --check plugin/
```

Expected: all tests PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add plugin/ui/bundle.js
git commit -m "feat(ui): add StatsTab with live turn banner + usage history"
```

---

## Post-plan checklist

- [ ] Sideload the built `.bhplugin` into BaluHost and verify all 6 tabs render correctly
- [ ] On the System tab: confirm VRAM bar shows correct values from `rocm-smi`
- [ ] On the Stats tab: run a chat turn, confirm the live turn banner appears and disappears
- [ ] Confirm the poll interval dropdown saves and takes effect without page reload
