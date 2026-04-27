# Design: Workflow Commands + Per-Phase Model Config

**Date:** 2026-04-27  
**Status:** Approved

---

## Overview

Two tightly related features:

1. **Workflow Commands** — `/plan`, `/tasks`, `/next` as CLI slash commands that guide the user through a structured development cycle (clarify → spec → tasks → implement).
2. **Per-Phase Model Config** — WebApp settings UI allowing different Ollama models and parameters per workflow phase, with VRAM-fit warnings.

---

## Feature A: Workflow Commands

### Commands

| Command | Trigger | Mode value |
|---|---|---|
| `/plan <description>` | starts planning phase | `"plan"` |
| `/tasks [spec-file]` | decomposes spec into tasks | `"tasks"` |
| `/next [tasks-file]` | implements next open task | `"next"` |

### CLI Layer

The CLI detects these prefixes before sending. Each becomes a standard chat request to the existing WebSocket endpoint. The `mode` and `reset_history` fields are added to the JSON payload sent in the initial `start` message of the WS handshake (same place `turn_id` and `message` already live):

```python
{
  "message": "<description or empty>",
  "mode": "plan" | "tasks" | "next",
  "reset_history": False | True | True,   # plan=False, tasks=True, next=True
}
```

`reset_history: True` causes the backend to start with an empty history and load the relevant artifact directly instead.

### Backend: Mode Fragment Injection

`run_turn` receives an optional `mode: str | None`. When set, a small prompt fragment (~300–400 tokens) is prepended to the system prompt. The base system prompt is never replaced.

Fragments live in `plugin/prompts/`:

- `mode_plan.md` — instructs the agent to ask clarifying questions one at a time, then write the spec file to `.balucode/plans/YYYY-MM-DD-<slug>.md`
- `mode_tasks.md` — instructs the agent to read the spec, decompose into a markdown checkbox list, write `.balucode/plans/<slug>-tasks.md`
- `mode_next.md` — instructs the agent to find the first unchecked item in tasks.md, implement it, then update the checkbox (`- [ ]` → `- [x]`)

### Artifact Loading (tasks and next)

When `reset_history=True`, the context assembler skips history and instead loads the relevant file directly as a system message:

- `/tasks [path]`: reads the explicitly passed spec path, or if omitted, the most recently modified `.balucode/plans/*.md` that does not end in `-tasks.md`; injects as system message (~2000 tokens budget)
- `/next [path]`: reads the explicitly passed tasks path, or if omitted, the most recently modified `.balucode/plans/*-tasks.md`; injects as system message (~500 tokens budget)

This replaces RAG for cross-phase context. RAG still runs normally for code retrieval within the same turn.

### File Layout

```
<project-root>/
  .balucode/
    plans/
      2026-04-27-oauth-login.md          ← spec (written by /plan)
      2026-04-27-oauth-login-tasks.md    ← checklist (written by /tasks)
```

### Context Budget per Phase

| Phase | System+Fragment | Artifact | RAG | Repo-map | History | Total |
|---|---|---|---|---|---|---|
| plan | ~4500 | — | 4096 | 6144 | grows/trims | ≤32K |
| tasks | ~4200 | ~2000 | 4096 | 6144 | 0 (reset) | ≤32K |
| next | ~4200 | ~500 | 4096 | 6144 | 0 (reset) | ≤32K |

### Default Behavior

Without any mode flag, the agent behaves exactly as today. No existing functionality changes.

---

## Feature B: Per-Phase Model Config

### New Config Fields

Added to `BaluCodePluginConfig`:

```python
# Per-phase model overrides (None → falls back to chat_model)
plan_model: str | None = None
tasks_model: str | None = None
next_model: str | None = None

# Per-phase parameter overrides (None → falls back to global value)
plan_temperature: float | None = None
plan_context_window: int | None = None
tasks_temperature: float | None = None
tasks_context_window: int | None = None
next_temperature: float | None = None
next_context_window: int | None = None
```

`run_turn` resolves the effective model/params from `(mode, config)` before calling Ollama.

### WebApp Settings UI

New section "Workflow-Modelle" in the settings page. Three accordions (Plan / Tasks / Next), each containing:

- **Modell-Dropdown** — populated from `GET /ollama/models`
- **Temperature Slider** — 0.0–1.5, step 0.05
- **Context Window Input** — integer, min 2048
- **VRAM-Check Badge** — shown after model selection (see below)

Default state for all three: inherits from global model ("wie Standard").

### VRAM Check Service

New backend endpoint: `GET /vram-check?model=<name>&context_window=<n>`

Logic:
1. Query Ollama `POST /api/show` for model details → extract parameter count + quantization level
2. Estimate VRAM: `param_bytes = params_billions * quant_bytes_per_param`. KV-cache (`2 * context_window * layers * heads * head_dim * dtype_bytes`) is added if Ollama exposes architecture details; otherwise a fixed 15% overhead is assumed.
3. Query ROCm via `rocm-smi --showmeminfo vram --json` for available VRAM (Sven's RX 7900 XT: 20 GB)
4. Fallback if `rocm-smi` unavailable: return estimate only, no comparison

Response:
```json
{
  "model_vram_estimate_gb": 9.2,
  "available_vram_gb": 18.5,
  "fits": true,
  "warning": null
}
```

If `fits: false`, the WebApp shows a warning toast and a persistent badge on the accordion:  
> "⚠ Modell passt möglicherweise nicht in den VRAM. Performance kann stark degradieren."

**Does not block saving.** User decides.

Additionally, when a model is selected that fits but leaves less than 2 GB headroom, a softer performance warning is shown:  
> "ℹ Wenig VRAM-Puffer — Generierungsgeschwindigkeit kann variieren."

---

## Error Handling

- If `.balucode/plans/` contains no spec when `/tasks` is called: agent returns an error message, no turn started.
- If tasks file has no unchecked items when `/next` is called: agent reports "Alle Tasks erledigt."
- VRAM check failure (rocm-smi not found, Ollama unreachable): silently skipped, no badge shown.

---

## Out of Scope (v1)

- Web-App-triggered workflow commands (only CLI for now)
- `/review` or `/done` commands
- Automatic phase detection without explicit command
- Per-project model config (global config only)
