# Balu Code WebApp v2 — System Monitor + Stats Design

**Date:** 2026-04-26  
**Status:** Approved  
**Scope:** Two new tabs (System, Stats), three new backend routes, agent-loop metrics, config extension.

---

## Goals

- Show live hardware utilization (VRAM, GPU %, loaded models) in a dedicated System tab
- Show historical usage stats (requests, tokens, tools, approval rate) + live turn indicator in a Stats tab
- Keep the frontend a single no-build-step JS file using `window.React`
- All new backend logic is tested; JS is visually verified via sideload

---

## Tab Structure (after this phase)

| # | Tab | Content |
|---|-----|---------|
| 1 | Models | Existing — list of Ollama models with chat/embed badges |
| 2 | Projects | Existing — create/delete/index projects |
| 3 | Config | Existing — plugin config form, extended with `poll_interval_seconds` |
| 4 | Logs | Existing — audit log table |
| 5 | System | New — GPU/VRAM widget + loaded models table, auto-polling |
| 6 | Stats | New — live turn banner + 7-day history + by-model + top tools + approval summary |

---

## Architecture

```
New backend
├── GET /system           → OllamaClient.ps() + services/system.py (GPU subprocess)
├── GET /turns/current    → services/active_turn.py (in-memory singleton)
└── GET /stats            → AuditLogger.query_stats() (DB aggregation)

Agent-loop extension
└── run_turn: set_active() on start, clear_active() in finally
              record_turn_end() at TurnEnd (saves Ollama final-frame metrics)

Config extension
└── poll_interval_seconds: int = 10  (min: 3)

Frontend
├── SystemTab  — polls /system every poll_interval_seconds (hard floor: 3s)
└── StatsTab   — loads /stats + /turns/current on mount; polls /turns/current every 5s
```

---

## Section 1: Config Extension

**File:** `plugin/config.py`

Add one field to `BaluCodePluginConfig`:

```python
poll_interval_seconds: int = Field(default=10, ge=3, le=300)
```

Also add to `ConfigUpdateRequest` in `plugin/schemas.py`:
```python
poll_interval_seconds: int | None = Field(default=None, ge=3, le=300)
```

The Config-Tab UI already renders all config fields dynamically from `CONFIG_FIELDS` — add one entry:
```javascript
{ key: 'poll_interval_seconds', label: 'System poll interval (s, min 3)', type: 'number' }
```

---

## Section 2: `GET /system`

### New file: `plugin/services/system.py`

Provides `get_gpu_info() -> dict | None`:

1. Try `rocm-smi --json` (timeout 2s, `check=False`)
2. Fallback: `nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits` (timeout 2s)
3. If both fail or raise `FileNotFoundError`: return `None`

Returns dict:
```python
{
    "available": True,
    "backend": "rocm",          # or "nvidia"
    "utilization_pct": 42,
    "vram_used_bytes": 10_500_000_000,
    "vram_total_bytes": 21_474_836_480,
}
```

### New method: `OllamaClient.ps() -> list[dict]`

Calls `GET /api/ps`, returns list of:
```python
{ "name": str, "size_vram": int, "context_length": int }
```
Gracefully returns `[]` if Ollama unreachable (same error hierarchy as `list_models`).

### Route response schema (`plugin/schemas.py`)

```python
class LoadedModel(BaseModel):
    name: str
    size_vram: int
    context_length: int

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

### Route

```python
@router.get("/system", response_model=SystemResponse, tags=["balu_code"])
async def get_system_route(
    _user: UserPublic = Depends(get_current_user),
    ollama: OllamaClient = Depends(get_ollama_client),
) -> SystemResponse:
```

Calls `ollama.ps()` and `asyncio.to_thread(get_gpu_info)` concurrently via `asyncio.gather`.

### System-Tab UI

- **VRAM bar**: filled portion = `size_vram` summed from loaded models / `vram_total_bytes` from GPU info. If `gpu.available` is false (no rocm-smi/nvidia-smi), show only raw text `X.X GB loaded` without a progress bar — no total means no ratio.
- **GPU utilization**: percentage badge, hidden if `gpu.available` is false.
- **Loaded models table**: Name / VRAM (GB) / Context Length / Badges (chat, embed)
- **Polling indicator**: `Updated 3s ago · every 10s`
- **Interval dropdown**: 3s / 5s / 10s / 30s — onChange calls `PUT /config` immediately, updates local poll interval

---

## Section 3: `GET /turns/current`

### New file: `plugin/services/active_turn.py`

Module-level singleton (same pattern as `deps.py`):

```python
@dataclass
class ActiveTurn:
    turn_id: str
    model: str
    started_at: datetime
    iterations: int
    username: str

_active: ActiveTurn | None = None

def set_active(turn: ActiveTurn) -> None: ...
def update_iterations(turn_id: str, count: int) -> None: ...
def clear_active(turn_id: str) -> None: ...
def get_active() -> ActiveTurn | None: ...
```

`run_turn` in `agent_loop.py` calls:
- `set_active(ActiveTurn(...))` at turn start
- `update_iterations(ctx.turn_id, iteration_count)` after each iteration
- `clear_active(ctx.turn_id)` in the `finally` block

### Route response schema

```python
class TurnCurrentResponse(BaseModel):
    active: bool
    turn_id: str | None = None
    model: str | None = None
    started_at: str | None = None   # ISO8601
    elapsed_seconds: int | None = None
    iterations: int | None = None
    username: str | None = None
```

### Route

```python
@router.get("/turns/current", response_model=TurnCurrentResponse, tags=["balu_code"])
async def get_turns_current(
    _user: UserPublic = Depends(get_current_user),
) -> TurnCurrentResponse:
```

No auth bypass needed — reads from in-memory state only.

---

## Section 4: Agent-Loop Metrics + `GET /stats`

### `AuditLogger` extension (`plugin/services/audit.py`)

**New method: `record_turn_end`**

Called from `run_turn` at TurnEnd, passing the Ollama final-frame fields:

```python
async def record_turn_end(
    self,
    *,
    turn_id: str,
    model: str,
    username: str,
    prompt_eval_count: int,     # tokens in
    eval_count: int,             # tokens out
    eval_duration_ns: int,       # nanoseconds
    total_duration_ms: int,
    iterations: int,
) -> None:
```

Stored as `action="turn:end"`, `resource=model`, `details` contains all fields plus computed `tokens_per_s = eval_count / (eval_duration_ns / 1e9)`.

If the final frame is absent (cancelled turn, model error), call with `eval_count=0`, `eval_duration_ns=0`.

**New method: `query_stats`**

```python
async def query_stats(self, days: int = 7) -> dict:
```

Returns:
```python
{
    "last_n_days": [
        { "date": "2026-04-26", "requests": 12, "tokens_in": 45000, "tokens_out": 8200 }
    ],
    "by_model": [
        { "model": "qwen2.5-coder:14b", "requests": 45, "avg_tokens_per_s": 18.4 }
    ],
    "top_tools": [
        { "tool": "read_file", "calls": 120, "success_rate": 0.98 }
    ],
    "approval_summary": { "auto_approved": 80, "user_approved": 15, "rejected": 3 }
}
```

Aggregation is done in a single `_query_stats_sync` method on a thread. Queries:
- `turn:end` entries for requests/day and token counts
- `tool:*` entries for top tools and approval summary (`details.auto_approved`, `details.approved`)

### Response schema (`plugin/schemas.py`)

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

### `GET /stats` route

```python
@router.get("/stats", response_model=StatsResponse, tags=["balu_code"])
async def get_stats_route(
    days: int = Query(default=7, ge=1, le=90),
    _user: UserPublic = Depends(get_current_user),
    audit_log: AuditLogger = Depends(get_audit_log),
) -> StatsResponse:
    return await audit_log.query_stats(days=days)
```

### Stats-Tab UI

- **Live banner** (polls `/turns/current` every 5s):
  - Active: `⬤  qwen2.5-coder:14b · 3 iterations · 00:42 · sven`
  - Idle: subtle grey `No active turn`
- **Last 7 days table**: Date / Requests / Tokens In / Tokens Out
- **By-model table**: Model / Requests / Avg Tokens/s
- **Top tools table**: Tool / Calls / Success Rate (as %)
- **Approval summary**: three badges — `auto: 80 · user: 15 · rejected: 3`
- **Refresh button** top-right (re-fetches `/stats`)

---

## New + Modified Files

| File | Action |
|------|--------|
| `plugin/config.py` | Modify — add `poll_interval_seconds` |
| `plugin/schemas.py` | Modify — add `LoadedModel`, `OllamaSystemInfo`, `GpuInfo`, `SystemResponse`, `TurnCurrentResponse`, `ConfigUpdateRequest.poll_interval_seconds` |
| `plugin/services/system.py` | Create — `get_gpu_info()` |
| `plugin/services/ollama_client.py` | Modify — add `ps()` method |
| `plugin/services/active_turn.py` | Create — `ActiveTurn`, `set/clear/get_active`, `update_iterations` |
| `plugin/services/audit.py` | Modify — add `record_turn_end()`, `query_stats()` |
| `plugin/services/agent_loop.py` | Modify — call `set_active`, `update_iterations`, `clear_active`, `record_turn_end` |
| `plugin/routes.py` | Modify — add `GET /system`, `GET /turns/current`, `GET /stats` |
| `plugin/ui/bundle.js` | Modify — add `SystemTab`, `StatsTab`, poll interval dropdown in Config tab |
| `plugin/tests/test_system.py` | Create — tests for `get_gpu_info`, `OllamaClient.ps()` |
| `plugin/tests/test_routes_system_stats.py` | Create — tests for the 3 new routes |
| `plugin/tests/test_active_turn.py` | Create — tests for `active_turn.py` |
| `plugin/tests/test_audit_stats.py` | Create — tests for `record_turn_end`, `query_stats` |

---

## Testing Strategy

All new Python modules get unit tests with mocked dependencies. No real Ollama or GPU hardware needed:
- `system.py`: mock `subprocess.run` to return fixture JSON
- `OllamaClient.ps()`: mock transport (same pattern as existing `list_models` tests)
- `active_turn.py`: pure in-memory, no mocks needed
- `audit.py` new methods: mock `SessionLocal` (same pattern as `query_recent_tool_calls` tests)
- Route tests: override `get_audit_log`, `get_ollama_client` deps (same pattern as `test_routes_config_logs.py`)

JS bundle: no automated tests — visually verified via sideload.

---

## Non-Goals (v2 / later)

- WebSocket push for system metrics (polling at ≥3s is sufficient)
- Historical charts / graphs (Recharts, D3 — not worth the dependency)
- Per-project stats breakdown
- VRAM prediction / "will this model fit?" advisor
