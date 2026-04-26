# Balu Code — Phase 5a Design (CLI: Auth + Init + Chat REPL)

**Status:** draft, user-approved  
**Date:** 2026-04-26  
**Depends on:** Phase 4b (write tools + approval gate + WS `/chat`) shipped on `main`

---

## §1 — Architecture & Scope

Phase 5a delivers a working terminal client: you can authenticate, initialise a project, and drive the coding agent from your shell. The Textual TUI, session storage, and `config get|set` are deferred to Phase 5b.

**Commands in scope:**
- `auth login` / `auth status`
- `init`
- `models`
- `index`
- `chat` (interactive REPL)

**Out of scope (→ 5b):** Textual TUI, `session list/resume/delete`, `config get|set`.

**Implementation approach:** asyncio + Rich (Option A). Every Typer command is synchronous and calls `asyncio.run()` internally where needed. The WebSocket client is a thin `async def` wrapper using the `websockets` library. `httpx` handles REST (already present in the project for `web_fetch`). No threading.

**New dependencies:**
```
websockets>=13
rich>=13
pyyaml>=6
respx>=0.21   # dev/test only
```

**Module structure:**
```
cli/src/balu_code_cli/
  __init__.py             # __version__
  __main__.py             # typer app, registers all subgroups + commands
  commands/
    auth.py               # login, status
    init.py               # init wizard
    models.py             # list models
    index.py              # trigger + poll index job
    chat.py               # interactive REPL
  client/
    http.py               # httpx REST wrapper (auth header injection, base URL)
    ws.py                 # asyncio WS client, frame dispatch, async generator
  config/
    paths.py              # XDG-aware ~/.config/balu-code/ path constants
    loader.py             # config.yaml + credentials.yaml read/write (Pydantic)
    permissions.py        # permissions.yaml read/write/lookup (Pydantic)
    balucode_yaml.py      # .balucode.yaml parser (Pydantic)
```

Each command imports only its client + config layer — no cross-command imports.

---

## §2 — Config & Credentials

Three files under `~/.config/balu-code/` (created on first use, no crash if absent):

### `config.yaml`
```yaml
server_url: https://balu.example.com
default_project_id: 42
```
Pydantic model `AppConfig`. Written by `auth login` and `init`.

### `credentials.yaml` (mode `0600`)
```yaml
servers:
  https://balu.example.com:
    api_key: "bc_..."
```
Pydantic model `Credentials`. Written by `auth login`. Mode is enforced on every write: `chmod(path, 0o600)`. Multiple servers supported — `auth login` adds or overwrites a single entry keyed by server URL.

### `permissions.yaml`
```yaml
permissions:
  https://balu.example.com:
    "42":
      write_file: true
      apply_patch: true
      run_bash: false
      web_fetch: true
```
Pydantic model `PermissionsStore`. Keys are `server_url → str(project_id) → tool_name → bool`. A missing key means "ask interactively". Written by the chat approval flow (on `Y`/`N` responses). `--yolo` bypasses the file entirely.

**Config loader contract:**
- `load_config() -> AppConfig` — reads config.yaml, returns defaults if absent
- `load_credentials() -> Credentials` — reads credentials.yaml, returns empty if absent
- `save_credentials(creds)` — writes + chmods
- `load_permissions() -> PermissionsStore` — reads permissions.yaml, returns empty if absent
- `save_permissions(perms)` — writes (no chmod needed, not secret)

All read/write is via `pyyaml` + Pydantic `model_validate` / `model_dump`. No partial updates — always load-modify-save the full file.

---

## §3 — `.balucode.yaml` Parser

Written by `init` into the current working directory. Read by `chat` to determine project context and tool policy.

```yaml
project_id: 42
server_url: https://balu.example.com
model: llama3.1:8b        # optional, overrides server default
tools:
  allow_write: false       # write_file, apply_patch
  allow_bash: false        # run_bash
  allow_web_fetch: true    # web_fetch
```

Pydantic model `BaluCodeYaml` in `config/balucode_yaml.py`. `chat` searches for `.balucode.yaml` by walking up from cwd (like git does). If not found → error with helpful message ("run `balu-code init` first").

**`allow_*` fields and permissions interaction:**
- If `allow_write: true` → those tools are auto-approved (no prompt, no permissions lookup)
- If `allow_write: false` (default) → check `permissions.yaml` → if entry exists use it → else prompt

`--yolo` overrides everything: all approvals are `True`, no prompts, no permissions lookup.

---

## §4 — Commands

### `auth login`
1. Prompts: server URL (default from config.yaml if present), API key
2. `GET <server>/api/plugins/balu_code/health` with `Authorization: Bearer <key>`
3. On success: writes credentials.yaml + config.yaml (server_url), prints confirmation
4. On failure: prints error, exits non-zero (nothing written)

### `auth status`
1. Reads config.yaml + credentials.yaml
2. `GET /health` live check
3. Rich table: Server URL, API key prefix (first 8 chars + `...`), status (✓ ok / ✗ unreachable)

### `init`
Wizard — prompts one field at a time:
1. Server URL (default from config.yaml)
2. Project name
3. Root path (default: cwd, must be absolute)
4. Model (fetches list from `/models`, lets user pick)

Then: `POST /projects` → gets `project_id` back. Writes `.balucode.yaml` into cwd. Prints: "Project #42 initialised. Run `balu-code index` to build the RAG index."

If `.balucode.yaml` already exists → asks "Overwrite? [y/N]".

### `models`
`GET /models` → Rich Table with model name column.

### `index`
1. `POST /projects/{id}/index`
2. Polls `GET /projects/{id}/index/status/{job_id}` every 2s with Rich spinner
3. On done: prints files indexed + chunk count

### `chat`
```
balu-code chat [--yolo] [--project-id ID]
```
- `--project-id` overrides `.balucode.yaml` project_id (useful for one-off sessions)
- `--yolo` auto-approves all tool calls, no prompts

**REPL loop:**
```
[balu-code] > _
```
1. Read line from stdin (`prompt_toolkit` or plain `input()`)
2. If empty → skip. If `.exit` / `.quit` → close WS, exit.
3. Send `UserMessage(content=line)` over WS
4. Dispatch events until `TurnEnd` (see §5)
5. Print blank line, show prompt again
6. Ctrl+C during turn → send `Cancel(turn_id=...)`, print `[yellow]Cancelled[/yellow]`, back to prompt
7. Ctrl+C at prompt (no active turn) → exit cleanly

---

## §5 — WebSocket Client & Event Dispatch

**`client/ws.py`** exposes:
```python
async def connect(server_url, api_key, project_id) -> AsyncContextManager[BaluCodeWS]:
    ...

class BaluCodeWS:
    async def send_message(self, content: str) -> None: ...
    async def send_approval(self, tool_call_id: str, approved: bool, reason: str | None) -> None: ...
    async def send_cancel(self, turn_id: str) -> None: ...
    async def receive(self) -> Event: ...  # parses via shared events.parse_frame
```

Auth: `Authorization: Bearer <api_key>` passed as extra header in the WS handshake (`websockets.connect(..., additional_headers={...})`).

**Event dispatch in `chat.py`:**

| Event | Rich output |
|-------|-------------|
| `turn_start` | Store `turn_id`, show spinner "Thinking…" |
| `token` | Stop spinner on first token; `print(content, end="", flush=True)` |
| `tool_call` | `\n🔧 tool_name(key=val, ...)` — auto_approved shown as `[dim](auto)[/dim]` |
| `approval_request` | Approval flow (see below) |
| `tool_result` | `  ✓ ok (N bytes)` or `  ✗ error: message` |
| `turn_end` | Print `\n`, clear turn state |
| `error` | `[red]Error [code]: message[/red]` |

**Approval flow (on `approval_request`):**

Priority order (first match wins):
1. `--yolo` flag → auto-approve, skip all steps below
2. `.balucode.yaml` `allow_*: true` for this tool's risk group → auto-approve silently
3. `permissions.yaml` has entry for this server+project+tool → use stored decision silently
4. Otherwise: print a Rich panel and prompt:
   ```
   ┌─ Approval required ──────────────────────────────┐
   │ Tool:  write_file  [risk: write]                 │
   │ Args:  path="src/foo.py"  content="..."          │
   └──────────────────────────────────────────────────┘
   Allow? [y]es / [n]o / [Y]es always / [N]o always >
   ```
5. `Y` or `N` → persist to permissions.yaml, then use that decision
6. Send `Approval(tool_call_id=..., approved=bool)`

---

## §6 — Testing

**Config layer** (`config/`): pure unit tests with `tmp_path`. Test Pydantic parsing, YAML round-trip, `0600` mode enforcement on credentials write, permissions lookup (present/absent/--yolo).

**HTTP client** (`client/http.py`): `respx` mocks for all REST endpoints. Tests for auth header injection, error propagation.

**WS client** (`client/ws.py`): `pytest-asyncio` + `websockets.serve()` local test server. Scripted frame sequences → assert client returns correct `Event` objects.

**Commands**: Typer `CliRunner` for all commands. HTTP calls mocked via `respx`. `chat` command receives a `ws_factory` dependency that the test overrides with a fake WS client returning scripted events. Approval prompts tested via mocked `input()`.

**No integration tests against a live BaluHost in 5a** — all tests are offline.

---

## §7 — Error Handling & Edge Cases

- **No `.balucode.yaml` found** → `chat` / `index` print "Run `balu-code init` first" and exit non-zero
- **Server unreachable** → Rich error, non-zero exit, no crash
- **WS disconnect mid-turn** → print "Connection lost", back to prompt (or exit if unrecoverable)
- **credentials.yaml missing** → `chat` / `models` / `index` print "Run `balu-code auth login` first"
- **API key invalid (401)** → clear error message, hint to re-run `auth login`
- **`permissions.yaml` corrupt YAML** → warn + treat as empty (don't crash)
- **`--yolo` + `allow_bash: false` in `.balucode.yaml`** → `--yolo` wins (CLI flag > config file)

---

## §8 — Phase 5b Preview (out of scope here)

- Textual TUI: streaming bubble, tool-call cards with diff viewer, `e` opens `$EDITOR`
- `session list/resume/delete` — JSONL storage at `~/.local/share/balu-code/sessions/`
- `config get|set` — edit config.yaml from CLI
