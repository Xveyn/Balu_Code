# Opencode Runtime Integration — Design

**Date:** 2026-05-14
**Author:** Sven (Xveyn) + Claude
**Status:** Approved by user, ready for implementation planning
**Scope:** Replace Balu_Code's internal Python-based coding agent with an embedded
[opencode](https://github.com/Xveyn/opencode/tree/dev) runtime. The Balu_Code plugin
becomes a thin BaluHost adapter around opencode.

## Why

Balu_Code v0.1.0 ships a self-built coding agent in Python: agent loop, context
assembler, tool registry, RAG indexer, repo map, Ollama client. Maintaining all
of this is a heavy investment for one maintainer, and opencode already provides
a production-grade coding agent with broader tool coverage (edit, apply_patch,
shell, lsp, grep, glob, webfetch, mcp), better prompts, compaction, permissions,
and an HTTP server with an openapi spec — usable from any language.

Decision: stop maintaining a parallel implementation. Use opencode as the agent
runtime, keep only the BaluHost integration glue in Python.

## Architectural decisions (fixed before this spec)

These were settled during brainstorming and are not reopened here:

1. **Integration mode:** opencode runs as an embedded HTTP server (subprocess),
   Balu_Code plugin talks to it via REST + SSE.
2. **Python code scope:** the internal agent is replaced wholesale. Only the
   BaluHost adapter layer remains in Python (routes, auth, audit, config UI,
   project store).
3. **Process model:** one global opencode server per plugin instance, shared by
   all user sessions. Sessions/projects are isolated via opencode's own
   session IDs.
4. **Config source-of-truth:** Balu_Code's existing config store stays SoT.
   Plugin generates `opencode.json` from it. User sees one UI.
5. **Runtime distribution:** vendored standalone opencode binary, downloaded
   into the plugin data directory on first start, SHA256-verified against a
   pinned checksum.
6. **CLI:** the existing `cli/` component is dropped. Users invoke `opencode`
   CLI directly if they want a terminal client.

## Architecture

### Components that remain in Python

```
plugin/
├── routes.py           FastAPI routes (sessions, projects, stream-proxy)
├── schemas.py          Pydantic models matching opencode openapi.json
├── config.py           Plugin config (Ollama URL, default model, tool permissions)
├── config_store.py     User settings persistence
├── project_store.py    Workspaces / project paths (BaluHost-side)
├── data_dir.py
├── audit.py            AuditLogger (BaluHost permission events + tool calls)
├── ui/                 Existing settings UI
├── prompts/            Optional override templates
└── services/
    ├── opencode_runtime.py    [NEW]  Binary lifecycle: download, start, stop, health
    ├── opencode_client.py     [NEW]  HTTP/SSE client against opencode server
    ├── opencode_config.py     [NEW]  Generates opencode.json from Balu_Code config
    └── session_bridge.py      [NEW]  Maps Balu_Code project_id ↔ opencode session_id
```

### Components removed

```
services/agent_loop.py, active_turn.py, cancel.py
services/context_assembler.py, system.py, tokenizer.py
services/indexer.py, index_jobs.py
services/rag_chunker.py, rag_index.py, rag_registry.py
services/repo_map.py, repo_map_types.py
services/ollama_client.py
services/parsers/        (tree-sitter integration)
services/tools/          (entire tool registry + implementations)
cli/                     (separate package, dropped)
```

### Data directory layout

```
~/.local/share/baluhost/plugins/balu_code/data/
├── runtime/
│   ├── opencode-linux-x86_64           Active binary
│   └── opencode-linux-x86_64.previous  Last version (kept 30 days for rollback)
├── opencode.json                       Generated config (from Balu_Code config_store)
├── opencode.log                        opencode server stdout/stderr (rotated at 100 MB)
└── runtime.lock                        Port allocation + pid file
```

### High-level request flow

```
Browser
  │
  ▼  POST /api/plugins/balu_code/chat/{project_id}  { messages, model }
routes.py
  ├─ audit.log(action="chat.send", project=...)
  ├─ session_id = session_bridge.get_or_create(project_id)
  └─ async for event in opencode_client.session_send(session_id, messages, model, stream=True):
        ├─ if event.type == "tool.use": audit.log(action=f"tool.{event.name}", args=event.args)
        └─ yield event   (SSE proxy to browser)
        │
        ▼
opencode server (port 4096, subprocess)
  ├─ POST /session/{id}/message
  ├─ runs session/processor.ts
  ├─ tools execute under plugin uid (inherits BaluHost permissions)
  ├─ calls Ollama at configured URL
  └─ streams SSE events back
```

## Component contracts

### `opencode_runtime.py`

Responsibilities: binary download, process lifecycle, health, watchdog.

Public API:
- `ensure_binary() -> Path` — download + verify if missing, return path
- `start_server(config_path: Path) -> ServerHandle` — spawn, wait for health
- `stop_server(handle: ServerHandle) -> None` — SIGTERM, 5s grace, SIGKILL
- `is_healthy(handle) -> bool`
- `watchdog_task()` — asyncio task, polls /health every 30s, auto-restarts up to 3× per 5min

Pinned values:
- `OPENCODE_VERSION = "<version>"` — bumped explicitly per plugin release
- `BINARY_CHECKSUMS = {"linux-x86_64": "sha256:..."}` — hardcoded per version

### `opencode_client.py`

Responsibilities: typed REST/SSE client. Async (httpx).

Public API (subset, derived from opencode openapi.json):
- `create_session(cwd: Path) -> SessionId`
- `session_send(session_id, messages, model, *, stream=True) -> AsyncIterator[Event]`
- `session_abort(session_id) -> None`
- `health() -> bool`

SSE events are parsed into Pydantic models matching opencode's event schema.

### `opencode_config.py`

Pure function: `to_opencode_config(plugin_config: BaluCodePluginConfig) -> dict`.
Snapshot-testable. Writes to `data_dir/opencode.json`.

Maps:
- Balu_Code Ollama URL → opencode provider config
- Balu_Code default model → opencode default model
- BaluHost `file:write` permission missing → opencode `mode: "readonly"`

### `session_bridge.py`

Manages the `projects.opencode_session_id` column. Idempotent
`get_or_create(project_id) -> session_id`, falls back to creating a new
opencode session if the stored ID is invalid (server restart).

DB migration: `ALTER TABLE projects ADD COLUMN opencode_session_id TEXT`.

### `routes.py` (changes)

New endpoints:
- `POST /chat/{project_id}` — main chat, SSE stream, proxies to opencode
- `POST /chat/{project_id}/cancel` — calls `session_abort`
- `GET /runtime/status` — for UI degraded-state banner
- `POST /runtime/restart` — manual restart trigger

## Error handling and lifecycle

### Plugin boot

```
1. BaluHost loads plugin → __init__.py:on_enable()
2. opencode_runtime.ensure_binary()       (download if missing, verify checksum)
3. opencode_config.write_config()         (generate from config_store)
4. opencode_runtime.start_server()        (spawn subprocess)
5. opencode_client.wait_ready(timeout=15s)
6. Plugin signals ready to BaluHost; start watchdog task
```

On failure at step 2-5: plugin enters `degraded` state. Settings UI shows red
banner with last error and a "Retry" button. Chat routes return 503.

### Process crash

Watchdog polls `/health` every 30s. On failure:
- Restart up to 3 times within a 5-minute window
- If exceeded → degraded state, require manual restart

### Port conflict

If port 4096 is busy, allocate a random free port and write it to
`data_dir/runtime.lock`. Client reads the lock file on start.

### Streaming errors

- SSE drop mid-turn → emit `{type: "error", reason: "stream_lost"}` to browser,
  mark turn failed in audit log, session stays usable
- Ollama unreachable → opencode emits SSE error event, proxied 1:1 and audited
- Tool call error → opencode handles internally; surfaces as SSE event

### Permission changes

- BaluHost denies `file:write` → opencode config set to `mode: "readonly"`
- Permission changed live → server restart with new config

### Cancel and timeout

- UI cancel → `POST /chat/{pid}/cancel` → `session_abort`
- Hard timeout 10 min (configurable) → abort + error to UI

### Upgrade and rollback

- Plugin update with new opencode version: download new binary, move current to
  `opencode-linux-x86_64.previous`. Keep previous for 30 days. Manual rollback
  by renaming files; UI exposes a rollback button while `.previous` exists.

## Migration plan

Four phases, on a long-lived feature branch `feat/opencode-runtime`.

### Phase A — Build adapter (non-destructive, parallel to existing code)

1. Implement `services/opencode_runtime.py`
2. Implement `services/opencode_client.py`
3. Implement `services/opencode_config.py`
4. Implement `services/session_bridge.py` + DB migration
5. Add new route `POST /chat/v2/{project_id}` next to existing `/chat`
6. Smoke test: curl prompt → streamed response

### Phase B — Switch UI

7. Switch UI from `/chat` to `/chat/v2`
8. Feature flag for fast rollback
9. Manual E2E: prompt → edit tool → file changes → audit entry appears

### Phase C — Cleanup (single commit "feat(plugin): replace internal agent with opencode runtime")

10. Delete the modules listed under "Components removed"
11. `plugin.json`:
    - `python_requirements` shrinks: drop `tree-sitter*`, `tiktoken`, `sqlite-vec`,
      `trafilatura`, `unidiff`. Keep `httpx`, `pydantic`.
    - `required_permissions`: keep `db:read/write` (project_store, audit, config
      still use sqlite); other permissions unchanged.
12. Simplify `deps.py` to: `ProjectStore`, `AuditLogger`, `OpencodeRuntime`,
    `OpencodeClient`, `Config`
13. Delete obsolete tests (~150-200 of 291): all RAG / indexer / repo-map / tool
    / agent-loop tests

### Phase D — CLI

14. Drop `cli/` package entirely. Update docs to point users at `opencode` CLI
    directly.

**Estimated impact:** ~6000-8000 Python LOC removed, ~800-1200 LOC added.
Net reduction ≈ 5000 LOC.

## Test plan

### Unit + integration (Python side)

| Component | Approach |
|---|---|
| `opencode_runtime` | Unit: download mocked via httpx MockTransport, checksum verify real. Integration: spawn real binary in tmp_path, health polling, graceful shutdown. |
| `opencode_client` | Unit: respx mocks for all endpoints. Integration: live against locally started opencode (session-scoped fixture). |
| `opencode_config` | Snapshot tests for `config.py` → `opencode.json` mapping. |
| `session_bridge` | Unit: project_id ↔ session_id mapping, DB migration. |
| `routes.py` | FastAPI TestClient + mocked `opencode_client`. SSE proxy with fake SSE source. Tool-use events flow into audit. |
| `audit.py`, `config_store.py`, `project_store.py` | Existing tests stay. |

### Not covered on plugin side

- opencode tool logic — trusted
- opencode prompts — trusted
- LLM output quality — manual E2E

### Manual E2E (Phase B Definition of Done)

1. Fresh install → binary downloads → server up within 15s
2. New project, prompt "list files" → stream appears, `glob` tool call in audit
3. Prompt "create test.txt with hello" → file exists, `write` tool call in audit
4. Cancel mid-stream → stream stops cleanly, no leftover process
5. `pkill opencode` → watchdog restarts → next prompt works
6. Stop Ollama → prompt → clear error in UI, no hanging stream
7. Revoke `file:write` permission → server restarts readonly → edit prompt
   fails with clear message

### CI

- Existing GitHub Actions pipeline stays
- New job: download opencode binary in CI, run integration tests against real
  server (Linux runner)
- Skip on macOS/Windows runners until binaries are verified there

## Out of scope for this spec

- Multi-tenant isolation beyond opencode's own session scoping
- macOS/Windows binary verification (linux-x86_64 first, others follow)
- Alternative integration via ACP (opencode supports it; revisit if HTTP/SSE
  proves insufficient)
- Restoring any of the deleted RAG/indexer/repo-map features as opencode MCP
  tools (deliberately rejected during brainstorming — "complete replacement, keep
  only BaluHost layer")
