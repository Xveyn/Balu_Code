# Balu Code — Self-Hosted Coding Agent Plugin for BaluHost

**Status:** Spec
**Date:** 2026-04-18
**Scope:** Design a self-hosted coding agent that runs against a local Ollama instance on the BaluHost server and is driven from a terminal CLI on any machine. Ship as a BaluHost marketplace plugin (`balu_code`) plus a separately pip-installable CLI (`balu-code`). The server plugin owns inference routing, codebase indexing, and tool execution; the CLI owns UX, approvals, and streaming rendering.

## Problem

There is no open self-hosted equivalent to Claude Code / Aider that plugs into an existing NAS-like server and re-uses its auth, audit, and service infrastructure. Running Ollama alone is easy; the missing pieces are:

- A **context-engineering pipeline** (repo-map + RAG) that keeps prompt size small enough to run 14B-class models on consumer GPUs (20 GB VRAM) without sacrificing code-structure awareness.
- A **tool-calling agent loop** with safe file-writes and shell-exec, streamed to a terminal client.
- **Project-level configuration** (which model, which paths, which tools auto-approve) that a user can check into their repo alongside the code.
- **Packaging & distribution** that uses BaluHost's plugin marketplace (installable with one click) and PyPI for the CLI (installable everywhere via `pip`).

Balu Code fills that gap for a single-server single-user workflow first, and is structured so that multi-user support can be added later.

## Goals

- **Terminal-first UX.** `balu-code chat` on a laptop or server opens a streaming TUI with tool-call approvals. No browser required.
- **Run everywhere.** Same CLI binary on Linux/macOS/Windows (WSL), connects over HTTPS+WebSocket to the server plugin.
- **Context aware.** Tree-sitter repo-map always present in the prompt; RAG retrieval adds semantically-relevant chunks on demand. Pure-prompt mode falls back gracefully when indexing is disabled.
- **VRAM-efficient defaults.** Defaults target an AMD RX 7900 XT (20 GB ROCm): `qwen2.5-coder:14b-instruct-q4_K_M` for chat, `nomic-embed-text` for embeddings, 32 K context window.
- **Re-use BaluHost primitives.** Auth via existing `ApiKey` model. Audit trail via existing `audit_log`. Permission declarations via existing `PluginPermission` enum. UI bundle via existing `window.BaluHost` SDK.
- **Full agent capability from v1.** Read, write, patch, glob, grep, bash — all with per-tool approval gates and path-containment checks. `--yolo` flag for interactive overrides.
- **Project-local configuration.** `.balucode.yaml` at the repo root overrides server-side defaults.
- **Deterministic build.** One monorepo, one `make release` command produces a `.bhplugin` ZIP and a `balu-code-cli` wheel.

## Non-Goals (v1)

- **Multi-user sessions.** One `ApiKey` → one concurrent session. Multi-user queuing and per-user indices are a v2 concern.
- **Remote Ollama.** The plugin assumes Ollama runs on `127.0.0.1:11434` on the same host as the BaluHost backend. Routing to a separate inference host is tracked as v2.
- **Strong sandboxing.** v1 runs `run_bash` in the CLI's or server's own process tree, inside the project's working directory. Optional `firejail`/`bwrap` wrappers are configurable but not the default.
- **Non-text artifacts.** Images, PDFs, Jupyter outputs are not ingested in v1. Only text files matched by a glob ignore-list.
- **Fine-tuning / adapter loading.** Model choice is limited to what Ollama serves. LoRA/QLoRA workflows are out.
- **Cross-plugin coordination.** Balu Code does not emit or subscribe to other plugins' events in v1.
- **Index re-use across machines.** Each client indexes its own local copy of the codebase; server does not host a shared index of files it doesn't see.

## Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│                              Developer machine                             │
│                                                                           │
│  ┌──────────────────────────────┐                                         │
│  │  balu-code  (pip package)    │                                         │
│  │  • Textual TUI               │                                         │
│  │  • Streaming renderer        │                                         │
│  │  • Tool-approval prompts     │                                         │
│  │  • .balucode.yaml parser     │                                         │
│  │  • ~/.config/balu-code/      │                                         │
│  │  • Local Tree-Sitter walker  │                                         │
│  └─────────────┬────────────────┘                                         │
└────────────────┼──────────────────────────────────────────────────────────┘
                 │ HTTPS  Bearer balu_xxxxxxxx  (existing BaluHost API key)
                 │ + WebSocket for /chat streaming
                 ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                      BaluHost server  (/opt/baluhost)                     │
│                                                                           │
│  FastAPI main app                                                         │
│  │                                                                        │
│  ├── /api/plugins/balu_code/                                              │
│  │     POST /projects          → register a project                       │
│  │     POST /projects/{id}/index  → build/refresh RAG index               │
│  │     GET  /projects/{id}/repo_map  → compact tree-sitter map            │
│  │     GET  /models            → list available Ollama models             │
│  │     GET/PUT /config         → plugin-global defaults                   │
│  │     WS   /chat              → streaming agent loop                     │
│  │                                                                        │
│  └── plugin: balu_code (PluginBase subclass)                              │
│        ├─ ollama_client.py   ROCm-aware HTTP client (/api/chat, /embed)   │
│        ├─ repo_map.py        Tree-sitter parser, symbol graph, cache      │
│        ├─ rag_index.py       sqlite-vec, per-project index files          │
│        ├─ agent_loop.py      Tool loop, context assembler                 │
│        ├─ tools/             read_file, write_file, apply_patch,          │
│        │                     glob, grep, run_bash, web_fetch              │
│        ├─ project_store.py   SQLite (plugin-owned), Project/Session rows  │
│        └─ ui/bundle.js       Settings page rendered by BaluHost UI        │
│                                                                           │
│  Adjacent services used:                                                  │
│  • app.services.auth (ApiKey validation via existing dependency)          │
│  • app.services.audit.logger_db (AuditLog entries for every tool call)    │
│  • app.plugins.permissions (PluginPermission enum)                        │
│                                                                           │
│  Ollama  (systemd unit, 127.0.0.1:11434, ROCm backend)                    │
│   ├─ qwen2.5-coder:14b-instruct-q4_K_M   (chat / tool use)                │
│   └─ nomic-embed-text                    (embeddings)                     │
└───────────────────────────────────────────────────────────────────────────┘
```

### Two deployables, one repo

```
Balu_Code/                              (single Git repo, MIT-licensed, public)
├── plugin/                             ← becomes balu_code-<version>.bhplugin
│   ├── plugin.json
│   ├── __init__.py                     PluginBase subclass
│   ├── manifest.json                   (generated, internal metadata)
│   ├── services/
│   │   ├── ollama_client.py
│   │   ├── repo_map.py
│   │   ├── rag_index.py
│   │   ├── agent_loop.py
│   │   ├── project_store.py
│   │   └── tools/
│   │       ├── __init__.py             registry
│   │       ├── read_file.py
│   │       ├── write_file.py
│   │       ├── apply_patch.py
│   │       ├── glob.py
│   │       ├── grep.py
│   │       ├── run_bash.py
│   │       └── web_fetch.py
│   ├── schemas/                        Pydantic request/response/event schemas
│   ├── ui/
│   │   └── bundle.js                   settings + status page
│   ├── db/
│   │   └── schema.sql                  creates balu_code_projects, repo_map_cache
│   ├── prompts/
│   │   ├── system.md                   base system prompt
│   │   └── tool_use.md                 tool-use instructions
│   └── requirements.txt                httpx, tree-sitter, sqlite-vec, pyyaml, …
├── cli/                                ← becomes balu-code-cli-<version>.whl
│   ├── pyproject.toml                  (name: balu-code-cli, binary: balu-code)
│   ├── src/balu_code_cli/
│   │   ├── __main__.py                 typer app
│   │   ├── commands/                   init, chat, index, auth, models, config
│   │   ├── tui/                        textual widgets
│   │   ├── client/
│   │   │   ├── http.py                 httpx REST wrapper
│   │   │   └── ws.py                   WebSocket event parser
│   │   ├── config/
│   │   │   ├── project.py              .balucode.yaml schema
│   │   │   └── user.py                 ~/.config/balu-code/config.yaml
│   │   └── session/
│   │       └── store.py                ~/.local/share/balu-code/sessions/
│   └── tests/
├── shared/                             ← installed as editable-src into both
│   └── src/balu_code_shared/
│       ├── events.py                   WS event envelopes (Pydantic)
│       ├── tools.py                    tool-call envelopes (JSON Schema)
│       └── config.py                   shared config models
├── scripts/
│   ├── build_bhplugin.py               zips plugin/ + shared/ into .bhplugin
│   ├── build_wheel.py                  builds cli/ + shared/ into .whl
│   └── release.py                      tags, builds both, uploads
├── tests/                              cross-cutting integration tests
├── docs/
│   ├── superpowers/specs/              design docs (this file)
│   ├── install.md                      Ollama + ROCm setup on the server
│   ├── cli.md                          CLI reference
│   └── config.md                       .balucode.yaml reference
├── .github/workflows/
│   ├── ci.yml                          pytest (plugin + cli), lint
│   └── release.yml                     builds artifacts on tag
├── README.md
└── LICENSE
```

## Plugin (Server Side)

### plugin.json

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
    "file:read", "file:write", "file:delete",
    "system:execute", "system:info",
    "network:outbound",
    "db:read", "db:write",
    "event:emit", "task:background"
  ],
  "plugin_dependencies": [],
  "python_requirements": [
    "httpx>=0.27",
    "tree-sitter>=0.22",
    "tree-sitter-languages>=1.10",
    "sqlite-vec>=0.1.1",
    "pyyaml>=6.0",
    "pydantic>=2.6"
  ],
  "entrypoint": "__init__.py",
  "ui": { "bundle": "ui/bundle.js", "styles": null }
}
```

### Routes

All routes mount under `/api/plugins/balu_code/` and require a valid `ApiKey` (resolved by the existing `get_current_user_from_api_key` dependency).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/projects` | Register a project (body: `name`, `root_path`, optional `.balucode.yaml` blob). Returns `project_id`. |
| `GET`  | `/projects` | List projects for the caller. |
| `GET`  | `/projects/{id}` | Get one project, including current index status. |
| `DELETE`| `/projects/{id}` | Unregister, delete index file. |
| `POST` | `/projects/{id}/index` | Start/refresh RAG index (returns job_id). |
| `GET`  | `/projects/{id}/index/status` | Poll index progress. |
| `GET`  | `/projects/{id}/repo_map` | Compact tree-sitter map (bytes, symbols, imports). |
| `GET`  | `/models` | List models available on the local Ollama. |
| `GET`  | `/config` | Get plugin-global defaults. |
| `PUT`  | `/config` | Admin-only: update plugin-global defaults. |
| `WS`   | `/chat` | Streaming agent loop. See WebSocket protocol below. |

### Services

- **`ollama_client.py`** — HTTP client wrapping `/api/generate`, `/api/chat`, `/api/embeddings`, `/api/tags`. Exposes streaming iterators. Handles server-side 429s / 503s with backoff. Configurable base URL (default `http://127.0.0.1:11434`). ROCm is transparent — it is an Ollama-level concern.
- **`repo_map.py`** — Walks the project root honoring `.gitignore` + `.balucode.yaml:ignore`. Uses `tree-sitter-languages` for Python, TypeScript/JavaScript, Go, Rust, Java, C/C++. For each file extracts: top-level symbols (def/class/fn/struct/enum/interface), public API, imports. Builds a compact text representation within a token budget (default 6 K). Cache keyed on `(file_path, mtime, sha1[:8])` stored in `project_store` sqlite, so only changed files re-parse.
- **`rag_index.py`** — Per-project `sqlite-vec` database file at `<baluhost_data>/plugins/balu_code/indices/<project_hash>.db`. Chunks are (file, start_line, end_line, text, embedding_vec, sha256). Embeds via `nomic-embed-text` on Ollama. Query-time top-K default 8, configurable. Optional `mmap_mode=ram` loads the file into OS page cache on startup to trade RAM for latency.
- **`agent_loop.py`** — Main runtime. Contract:
  1. Receives user prompt + project_id over WS.
  2. Assembles context: system prompt + repo_map (if enabled) + top-K RAG chunks (if enabled) + recent session turns.
  3. Calls Ollama `/api/chat` with `tools=[…]` streaming.
  4. Parses stream; if the model emits a tool call, pauses streaming, sends `tool_call` WS event, waits for approval (or auto-approves from whitelist), executes, sends `tool_result` back to Ollama, continues.
  5. Hard cap on iterations (default 12) and total tokens (default 80 K) per turn.
- **`project_store.py`** — Plugin-owned SQLite file (`<baluhost_data>/plugins/balu_code/store.db`) with tables `projects` and `repo_map_cache`. Session/message history is **client-owned** (see *Session storage* below) — the server side is stateless per turn, which keeps the plugin simple and lets users delete local history without touching the server. Tables are created at `on_startup()` via idempotent `CREATE TABLE IF NOT EXISTS`, so the plugin is self-contained (installs on any BaluHost without migrations).

### Plugin config schema

Returned by `PluginBase.get_config_schema()`, persisted in `installed_plugins.config` as JSON. Per-project config (`.balucode.yaml`) overrides these values.

```python
class BaluCodePluginConfig(BaseModel):
    chat_model: str = "qwen2.5-coder:14b-instruct-q4_K_M"
    embed_model: str = "nomic-embed-text"
    ollama_base_url: str = "http://127.0.0.1:11434"
    context_window: int = 32768
    repo_map_budget: int = 6144
    rag_budget: int = 4096
    rag_top_k: int = 8
    max_iterations: int = 12
    max_total_tokens_per_turn: int = 80000
    default_auto_approve_tools: list[str] = ["read_file", "glob", "grep"]
    bash_wrapper: Literal["none", "firejail", "bwrap"] = "none"
    temperature: float = 0.2
    allow_web_fetch: bool = False
```

### UI bundle

A single settings page, mounted at `/plugins/balu_code` in the BaluHost UI via the existing bundle mechanism:

- **Models** — list Ollama-available models, click to set as default.
- **Projects** — table: name, root_path, last_indexed_at, index_size. Actions: re-index, delete.
- **Config** — edit the `BaluCodePluginConfig` values above.
- **Logs** — tail recent agent-loop events (errors, tool calls, token counts). Wrapper around `audit_log` filtered to `source="balu_code"`.

The bundle stays small (~40 KB, one `bundle.js`, no CSS in v1) and reuses `window.BaluHost.React`, `window.BaluHost.api` like other plugins.

## CLI (Client Side)

### Commands

| Command | Behaviour |
|---|---|
| `balu-code auth login --server <url>` | Prompts for an API key, stores it in `~/.config/balu-code/credentials.yaml` (mode 600). |
| `balu-code auth status` | Shows server URL, current key prefix, `GET /projects` ping result. |
| `balu-code init` | Interactive wizard in the current directory: detects git root, picks defaults, writes `.balucode.yaml`, calls `POST /projects`, triggers first index. |
| `balu-code models` | `GET /models` printed as a table, shows which is default. |
| `balu-code index [--rebuild]` | Triggers RAG index job for the current project, follows progress. |
| `balu-code chat [prompt]` | Starts the Textual TUI. If `prompt` is given, runs one turn non-interactively and exits. Otherwise opens interactive mode. |
| `balu-code config get\|set <key> [value]` | Read/write local `.balucode.yaml`. |
| `balu-code session list\|resume <id>\|delete <id>` | Manage local session history. |
| `balu-code --yolo chat ...` | Auto-approves every tool call (including bash). Requires `BALU_CODE_YOLO=1` env or explicit `--yolo` flag. |

### Config files

**`~/.config/balu-code/config.yaml`** (user-global):
```yaml
server: https://nas.example.com
default_project: ~/code/baluhost  # used when cwd has no .balucode.yaml
theme: dark
render_markdown: true
```

**`~/.config/balu-code/credentials.yaml`** (user-global, mode 0600):
```yaml
servers:
  https://nas.example.com:
    api_key_prefix: balu_Ab3x
    api_key: balu_Ab3x...full_secret...
```

**`.balucode.yaml`** (repo-local, committed or gitignored as the user prefers):
```yaml
project:
  name: baluhost
  root: .                       # relative to this file
  ignore:
    - node_modules/
    - .venv/
    - "*.pyc"
    - "**/*.min.js"

model:
  chat: qwen2.5-coder:14b-instruct-q4_K_M   # override plugin default
  embed: nomic-embed-text
  temperature: 0.2
  context_window: 32768

context:
  repo_map: true
  repo_map_budget: 6144
  rag:
    enabled: true
    top_k: 8
    budget: 4096
    mmap_mode: ram              # 'ram' | 'disk'

tools:
  auto_approve: [read_file, glob, grep]
  allow_write: true
  allow_bash: true
  allow_web_fetch: false
  bash:
    wrapper: none               # 'none' | 'firejail' | 'bwrap'
    working_dir: .
    timeout_s: 120

agent:
  max_iterations: 12
  max_total_tokens_per_turn: 80000
  system_prompt: null           # null → built-in, or path to .md override
```

### TUI

Built on Textual (Python). Layout:

```
┌─ session: feat/auth-refactor ──────────── model: qwen2.5-coder:14b ──────┐
│                                                                          │
│  user   ▌ Refactor the auth middleware to use the new ApiKey model       │
│                                                                          │
│  assist ▌ I'll start by reading the current middleware.                  │
│          [read_file backend/app/middleware/auth.py] ✓ auto-approved      │
│          ...                                                             │
│          Proposed change to backend/app/middleware/auth.py:              │
│                                                                          │
│           @@ -23,7 +23,9 @@                                              │
│           -    user = session.query(User).get(user_id)                   │
│           +    api_key = resolve_api_key(token)                          │
│           +    user = api_key.user                                       │
│                                                                          │
│          [apply_patch] Approve? (y/n/e=edit/s=show full)                 │
│                                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│  > _                                                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

- Streaming tokens render into the assistant bubble.
- Tool calls render as collapsible cards with status (`running`, `awaiting approval`, `approved`, `rejected`, `done`).
- Patch approvals show unified diffs. `e` opens `$EDITOR` with the proposed patch.
- `Ctrl+C` cancels the current turn (sends `cancel` WS frame).

### Session storage

```
~/.local/share/balu-code/
├── sessions/
│   └── <project_hash>/
│       ├── 2026-04-18_14-02-auth-refactor.jsonl
│       └── 2026-04-18_16-11-bug-hunt.jsonl
└── logs/
    └── balu-code.log
```

Each session is an append-only JSONL of events, same envelope as the WS protocol. `balu-code session resume` replays the log locally and re-connects to the server (server session is stateless per turn; full history is client-owned).

## Protocols

### Authentication

CLI sends `Authorization: Bearer <api_key>` on every request. API keys are issued via the existing BaluHost UI (Admin → API Keys → Create). The plugin reuses `app.api.deps.get_current_user_from_api_key` (already present in BaluHost) — no new auth code.

### REST (selected bodies)

`POST /api/plugins/balu_code/projects`
```json
{ "name": "baluhost", "root_path": "/home/sven/projects/BaluHost", "config": {...yaml as dict...} }
```
→ `201 Created { "project_id": 1, "index_status": "pending" }`

`GET /api/plugins/balu_code/models`
→ `200 OK { "models": [{"name":"qwen2.5-coder:14b-instruct-q4_K_M","size_bytes":9100000000,"quantization":"Q4_K_M"}, …] }`

### WebSocket chat protocol

URL: `wss://nas/api/plugins/balu_code/chat?project_id=1&session_id=…`

**Client → Server frames (JSON):**

```json
{ "type": "user_message", "content": "Refactor the auth middleware..." }
{ "type": "approval", "tool_call_id": "tc_01", "approved": true, "edited_args": null }
{ "type": "cancel" }
```

**Server → Client frames:**

```json
{ "type": "turn_start", "turn_id": "t_…", "model": "…", "context_tokens": 9840 }
{ "type": "token", "content": "I'll start by" }
{ "type": "tool_call", "tool_call_id": "tc_01", "tool": "read_file",
  "args": {"path": "backend/app/middleware/auth.py"}, "auto_approved": true }
{ "type": "tool_result", "tool_call_id": "tc_01", "status": "ok",
  "bytes_in": 0, "bytes_out": 2438 }
{ "type": "approval_request", "tool_call_id": "tc_02", "tool": "apply_patch",
  "args": {"path": "...", "diff": "..."}, "risk": "write" }
{ "type": "turn_end", "turn_id": "t_…", "total_tokens": 18432, "iterations": 3,
  "stop_reason": "done" | "max_iter" | "error" | "cancelled" }
{ "type": "error", "code": "ollama_unreachable", "message": "..." }
```

All envelope fields are defined in `shared/events.py` as Pydantic models so both sides share the same schema.

## Context Engineering

### Repo-Map

The repo-map is always in the prompt (up to `repo_map_budget`). Format is inspired by Aider: one block per file listing classes + functions + imports.

```
=== backend/app/middleware/auth.py (142 lines)
imports: fastapi, sqlalchemy, app.models.user, app.services.token_service
classes:
  class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next) -> Response
functions:
  def get_current_user_from_token(token: str) -> User | None
```

When over budget, a ranker sorts files by: (recently-edited, import-weight, opened-in-chat) and truncates from the bottom. The model sees the file path + symbol headers of "everything else" as a fallback stub.

### RAG

- **Chunking.** Each source file is chunked at semantic boundaries (top-level definitions from tree-sitter). Fallback to 40-line sliding windows with 10-line overlap for unparseable files or very long definitions.
- **Embedding.** `nomic-embed-text` via Ollama `/api/embeddings`. Batch size 32. Stored as `float32[768]` in `sqlite-vec`.
- **Retrieval.** Cosine similarity top-K against the user message (concatenated with the last-assistant message for continuation queries). K=8 default, budget = `rag_budget` tokens (4 K default).
- **Re-rank pass.** Simple keyword-boosting: chunks whose path or symbol names appear in the query get +15 % score.
- **Invalidation.** On `POST /projects/{id}/index` or file-mtime change detected during `repo_map.py` walk, affected chunks are re-embedded.

### Context assembly

Order in the chat request:
1. System prompt (`prompts/system.md`, ~800 tokens).
2. Tool-use instructions (`prompts/tool_use.md`, ~400 tokens).
3. Repo-map block (≤ `repo_map_budget`).
4. RAG chunks block (≤ `rag_budget`).
5. Session history (last N turns that fit).
6. Current user message.

If any section overflows the context window, drop in this order: (5) oldest turns → (4) lowest-score RAG chunks → (3) lowest-rank repo-map files. System prompt and tool-use instructions are never dropped.

## Agent Loop & Tools

### Loop

```
while iterations < max_iterations:
    stream = ollama.chat(messages, tools=tool_schemas, stream=True)
    for frame in stream:
        if frame.is_token:            emit token event
        elif frame.is_tool_call:      break
    if no tool_call:                  emit turn_end; return
    if tool.needs_approval:           emit approval_request; wait
    result = tool_registry.execute(tool_call, context)
    audit_log.write(tool_call, result)
    messages.append(tool_result)
    iterations += 1
emit turn_end(stop_reason="max_iter")
```

### Tool registry

Each tool is a class:

```python
class Tool(Protocol):
    name: str
    description: str
    args_schema: type[BaseModel]   # used to generate JSON schema for Ollama tool call
    risk: Literal["read", "write", "exec", "network"]

    async def execute(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...
```

`ToolContext` carries: project root, session_id, user_id, audit_log hook, approval callback, deadline.

### v1 tools

| Name | Risk | Default approval | Notes |
|---|---|---|---|
| `read_file` | read | auto | Path-containment check; max 2 MB returned. Binary detection rejects non-text. |
| `glob` | read | auto | Honors `.balucode.yaml:ignore`. Max 1000 results. |
| `grep` | read | auto | ripgrep-backed; max 500 matches. |
| `write_file` | write | interactive | Writes new file; fails if exists unless `overwrite=true`. Path-containment. |
| `apply_patch` | write | interactive | Unified diff applied with `patch -p0`, dry-run first, rolls back on reject. |
| `run_bash` | exec | interactive | Runs in `cwd`, optional `firejail`/`bwrap`, timeout 120 s default, stdout+stderr captured, max 1 MB output. |
| `web_fetch` | network | interactive | Only if `allow_web_fetch: true`. Plain GET, 5 MB cap, no cookies. |

All write/exec tools:
- Resolve paths to absolute, check `path.is_relative_to(project_root)`.
- Refuse symlink escapes (`os.path.realpath` vs `project_root.realpath()`).
- Write an `audit_log` row with `source="balu_code"`, `action=tool.name`, `metadata={args, result.status}`.

## Security

### Approval model

Two orthogonal knobs per tool:

- **Enabled** — is this tool available at all? Controlled by `.balucode.yaml:tools.allow_write`, `allow_bash`, `allow_web_fetch`. If a tool is disabled, the model never sees it in its tool schema list.
- **Auto-approved** — if the tool *is* enabled, does its call run without asking the user? Three layers combine:
  1. **Plugin-global whitelist** (`BaluCodePluginConfig.default_auto_approve_tools`) — admin-set in the UI, applies to every caller.
  2. **Project-local additions** (`.balucode.yaml:tools.auto_approve`) — extra tool names a user wants auto-approved for this repo.
  3. **CLI `--yolo` flag** — treats every enabled tool as auto-approved for one session. Writes a distinctive `audit_log` entry (`metadata.yolo=true`) for post-hoc review.

The effective auto-approve set is the union of layers 1 and 2. Users cannot *narrow* the admin whitelist (the plugin-global auto-approve is always in effect if the tool is enabled), only *widen* it. To take a tool off the table entirely, flip its enabled flag off — that removes it from the model's toolbox, regardless of any auto-approve rule.

### Path containment

Central helper in `plugin/services/paths.py`:

```python
def resolve_in_project(path: str, project_root: Path) -> Path:
    resolved = (project_root / path).resolve()
    if not resolved.is_relative_to(project_root.resolve()):
        raise PathEscapeError(path)
    return resolved
```

Every write tool calls this before touching the FS.

### Bash sandboxing (optional)

`bash_wrapper` option picks one of:
- `none` (default): direct `subprocess.run`, cwd locked to project root.
- `firejail`: `firejail --private-tmp --noprofile --net=none <cmd>` (user must install firejail).
- `bwrap`: `bwrap --ro-bind / / --bind <root> <root> --proc /proc --dev /dev --unshare-net --unshare-user <cmd>` (user must install bubblewrap).

Neither wrapper is installed by the plugin. Docs explain how to install per distro.

### Secrets handling

- API keys never written to logs, never echoed by the TUI.
- `.balucode.yaml` never contains the API key (only a server URL reference).
- Environment variables (`BALU_CODE_API_KEY`, `BALU_CODE_SERVER`) override on-disk credentials — useful for CI.

### Audit log

Every tool call produces one `audit_log` row. Fields: `timestamp`, `user_id`, `source="balu_code"`, `action=<tool_name>`, `metadata.project_id`, `metadata.session_id`, `metadata.args`, `metadata.status`, `metadata.yolo`. The existing BaluHost Audit page filters work out of the box.

## Defaults tuned for RX 7900 XT (20 GB ROCm)

| Setting | Default | Rationale |
|---|---|---|
| Chat model | `qwen2.5-coder:14b-instruct-q4_K_M` | ~9 GB VRAM, leaves ~11 GB for KV cache at 32 K ctx and ~1 GB for embedding model. Solid tool-calling. |
| Embed model | `nomic-embed-text` | ~300 MB VRAM, 768-dim, open. |
| Context window | 32 K | Fits comfortably in 20 GB with the 14 B model at Q4. |
| `repo_map_budget` | 6 K tokens | Empirically enough for ~300-file repos. |
| `rag_budget` | 4 K tokens | Leaves 20 K for history+user+tool-results. |
| `max_iterations` | 12 | Caps runaway loops; matches Aider's default. |
| `rag_top_k` | 8 | Balanced recall/cost. |
| `temperature` | 0.2 | Agent workloads want determinism. |
| `mmap_mode` | `ram` | On 32 GB-RAM NAS, loading ~200 MB index is free. |

Users with smaller VRAM override to `qwen2.5-coder:7b-instruct-q4_K_M` (~5 GB) and `context_window: 16384`. Users with more VRAM can swap to `:32b-instruct-q5_K_M` (~22 GB — borderline on 20 GB, comfortable on 24 GB).

## Ollama & ROCm Setup

The plugin does **not** install Ollama. `docs/install.md` documents the manual steps:

1. Install ROCm 6.1+ on the server (Debian/Ubuntu: `rocm` meta-package).
2. `curl -fsSL https://ollama.com/install.sh | sh` (the installer detects ROCm and picks the correct backend).
3. `systemctl enable --now ollama`.
4. `ollama pull qwen2.5-coder:14b-instruct-q4_K_M` and `ollama pull nomic-embed-text`.
5. In BaluHost → Plugins → Balu Code → Config, verify the model picker shows both.

The plugin's `on_startup()` does a health check against `http://127.0.0.1:11434/api/tags` and surfaces a clear UI warning if it fails.

## Testing

### Plugin unit tests (pytest)

- `test_ollama_client.py` — mocks `httpx` with recorded fixtures; verifies streaming parser, tool-call extraction, retry logic.
- `test_repo_map.py` — fixture projects (py, ts, go, rust); asserts symbol extraction and budget trimming.
- `test_rag_index.py` — in-memory sqlite-vec; asserts chunk boundaries, embedding insertion, top-K ordering.
- `test_agent_loop.py` — fake Ollama client that scripts a sequence of (token, tool_call, tool_result) frames; asserts approval gating, iteration cap, audit writes.
- `test_tools.py` — per-tool tests with a temp project root. Path-containment, symlink escape, output caps, binary rejection.

### CLI unit tests

- `test_config.py` — `.balucode.yaml` parsing and merging with user config.
- `test_ws_client.py` — `pytest-asyncio` + `wsproto`; fake server sends canned event sequences, asserts UI state.
- `test_commands.py` — typer `CliRunner` for each subcommand with HTTP mocked by `respx`.
- `test_tui.py` — Textual snapshot tests.

### Integration

- CI job brings up a mock Ollama container (`ollama/ollama:latest` CPU-only) loaded with `qwen2.5-coder:1.5b` (fast). Runs a scripted chat that exercises `read_file`, `grep`, `apply_patch` on a fixture project. Asserts final file state + audit rows. ROCm is not exercised in CI.
- Local dev loop: `make dev-ollama` brings up Ollama on 127.0.0.1, `make dev-plugin` runs BaluHost backend pointing at a dev plugin-dir, `make dev-cli` opens a textual session against it.

## Build & Release

- `scripts/build_bhplugin.py` — zips `plugin/` + bundled `shared/src/balu_code_shared/`, writes `plugin.json` at root, emits `dist/balu_code-<version>.bhplugin`. SHA-256 emitted alongside for the marketplace index.
- `scripts/build_wheel.py` — runs `python -m build` in `cli/` after copying `shared/src/balu_code_shared/` into the source tree (editable install for dev, vendored for release).
- `scripts/release.py` — bumps version in `plugin/plugin.json` and `cli/pyproject.toml`, tags the commit, pushes, and lets `.github/workflows/release.yml` attach both artifacts to the GitHub Release. A separate PR into `Xveyn/BaluHost-Plugin-Market` adds the plugin to `index.json`.
- PyPI publish for `balu-code-cli` via `twine` in the release workflow (requires `PYPI_TOKEN` secret).

## Open Questions

1. **Does the existing BaluHost `ApiKey` model support scoped permissions** (e.g., "this key can only talk to the balu_code plugin")? If yes, the plugin can require a scoped key and reject master keys. If no, we accept any valid key in v1 and scope is a v2 concern.
2. **Should `apply_patch` use GNU `patch` or a pure-Python implementation?** GNU patch is slightly more lenient but is an extra host dependency. Pure-Python `unidiff` is sufficient for clean diffs. Recommendation: pure-Python `unidiff`, fall back to `patch` only if available.
3. **Streaming tool results back into the prompt: do we truncate the same way on every iteration?** Long `grep` results could eat the context window across 5 iterations. Recommendation: keep per-tool-result cap (1 MB raw) but in-prompt representation is trimmed to 2 K tokens with a `[truncated, N more lines]` marker; the full output is in the session log.
4. **Should we support the Ollama `/api/generate` streaming format as a fallback** for models without `tools=` support? Recommendation: yes, but in v1 we restrict the model selector to known tool-calling-capable models (`qwen2.5-coder*`, `llama3.1*+`, `mistral-large*`, `deepseek-coder*`).
5. **Where does the plugin store its SQLite file on a BaluHost install?** The Marketplace spec suggests `<baluhost_data>/plugins/<name>/`. Confirm the variable name and create path at `on_startup()`.

## Out of Scope (explicit)

- BaluHost Web UI chat tab (the settings page is sufficient in v1; chat lives only in the CLI).
- Model marketplace / auto-download of models from within the plugin UI.
- Multi-project workspaces in one chat (one project per session).
- Non-Ollama inference backends (LM Studio, vLLM, OpenAI-compatible).
- Speech input/output, image inputs.
- Pair-programming mode (shared sessions across users).

## Rollout

1. Internal development: plugin side-loaded by symlinking `Balu_Code/plugin/` into `backend/app/plugins/installed/balu_code/` on the dev server.
2. Alpha: tagged `0.1.0`, `.bhplugin` attached to the GitHub release, manually installed via BaluHost UI.
3. Beta: added to `BaluHost-Plugin-Market/index.json` behind a `category: experimental` tag.
4. GA: bump `min_baluhost_version` if any plugin-system changes are needed, promote to `category: general`.
