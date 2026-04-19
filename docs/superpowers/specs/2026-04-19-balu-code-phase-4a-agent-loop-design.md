# Balu Code — Phase 4a: Reader-only Agent Loop + WS /chat

**Status:** Design
**Date:** 2026-04-19
**Parent spec:** [`2026-04-18-balu-code-design.md`](2026-04-18-balu-code-design.md)
**Predecessor phase:** Phase 3b ([design](2026-04-19-balu-code-phase-3b-rag-design.md), [plan](../plans/2026-04-19-balu-code-phase-3b-rag.md), shipped 2026-04-19 with 194 tests green)

## Scope

Phase 4a delivers the first end-to-end agent turn: a user sends a chat message over WebSocket, the server assembles a budget-trimmed prompt, streams tokens from Ollama, executes read-only tools when the model calls them, feeds tool results back into the conversation, and streams the final answer — all within configurable iteration and token limits.

The slice is explicitly "reader only":

- Three tools, all auto-approved: `read_file`, `glob`, `grep`.
- Three new subsystems: `tokenizer`, `context_assembler`, `agent_loop` (plus the tool registry).
- Two new WebSocket envelopes: `ToolCall`, `ToolResult`.
- Seven new `BaluCodePluginConfig` fields (context_window / repo_map_budget / rag_budget / rag_top_k / max_iterations / max_total_tokens_per_turn / temperature).

**Out of scope (deferred to Phase 4b):**

- Write/exec/network tools (`write_file`, `apply_patch`, `run_bash`, `web_fetch`).
- `approval_request` / `approval` / `cancel` WS frames.
- Generalised path-containment helper (Phase 4a inlines the check in `read_file.py`).
- Audit-log emission.
- Smart ranker (recently-edited / import-weight / opened-in-chat).
- `--yolo` flag (CLI-side).

## File Structure (this phase)

```
plugin/
├── plugin.json                       [mod: python_requirements +tiktoken]
├── requirements.txt                  [mod]
├── pyproject.toml                    [mod]
├── config.py                         [mod: +7 fields]
├── routes.py                         [mod: WS /chat handler]
├── prompts/
│   ├── system.md                     [new]
│   └── tool_use.md                   [new]
└── services/
    ├── tokenizer.py                  [new]
    ├── context_assembler.py          [new]
    ├── agent_loop.py                 [new]
    └── tools/
        ├── __init__.py               [new: ToolRegistry]
        ├── base.py                   [new: Tool Protocol, ToolContext, ToolResult]
        ├── read_file.py              [new]
        ├── glob_tool.py              [new]
        └── grep_tool.py              [new]

shared/src/balu_code_shared/
└── events.py                         [mod: +ToolCall, +ToolResult]

plugin/tests/
├── test_tokenizer.py                 [new]
├── test_context_assembler.py         [new]
├── test_tool_base.py                 [new]
├── test_tool_read_file.py            [new]
├── test_tool_glob.py                 [new]
├── test_tool_grep.py                 [new]
├── test_agent_loop.py                [new]
└── test_routes_chat.py               [new]

shared/tests/test_events.py           [mod: +ToolCall/ToolResult cases]
```

## WebSocket protocol (Phase 4a subset)

**URL:** `ws://.../api/plugins/balu_code/chat?project_id=<int>`

**Auth:** `Authorization: Bearer <api_key>` via the WebSocket upgrade headers. FastAPI's `@router.websocket("/chat")` accepts a `Depends(get_current_user)` dependency the same way an HTTP route does; the BaluHost stub's `get_current_user` wires the user through.

**Client → Server:** exactly one frame type in 4a.

- `{"type": "user_message", "content": "..."}` — existing Phase-1 envelope, unchanged.

**Server → Client:** six frame types.

- `{"type": "turn_start", "turn_id": "...", "model": "...", "context_tokens": N}` — emitted once per user message.
- `{"type": "token", "content": "..."}` — streamed as Ollama produces them.
- `{"type": "tool_call", "tool_call_id": "tc_...", "tool": "read_file", "args": {...}, "auto_approved": true}` — for every tool invocation.
- `{"type": "tool_result", "tool_call_id": "tc_...", "status": "ok"|"error", "bytes_out": N, "error": null|"..."}` — matching each `tool_call`.
- `{"type": "turn_end", "turn_id": "...", "total_tokens": N, "iterations": N, "stop_reason": "done"|"max_iter"|"error"}` — exactly one per turn.
- `{"type": "error", "code": "...", "message": "..."}` — only on unrecoverable mid-turn failure (e.g., `OllamaUnreachable`).

Phase 4b adds `approval_request`, `approval`, `cancel`, `stop_reason: "cancelled"`.

### Connection-scoped history

The server maintains a `list[dict]` of OpenAI-style messages (`role`/`content`/`tool_calls`/`name`) keyed to the WebSocket connection. Each incoming `UserMessage` appends to that list and triggers a turn. The assistant's final text plus any tool_calls are appended after the turn completes; each `tool` message is appended as it arrives. When the WebSocket disconnects, the history is discarded.

The `UserMessage(content: str)` envelope from Phase 1 stays unchanged; we do not ship a `history` priming frame in 4a. Phase 5's CLI `session resume` can request one via a follow-up spec.

## Envelope additions in `shared/events.py`

```python
class ToolCall(_FrozenBase):
    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str = Field(..., min_length=1)
    tool: str = Field(..., min_length=1)
    args: dict[str, Any]
    auto_approved: bool


class ToolResult(_FrozenBase):
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = Field(..., min_length=1)
    status: Literal["ok", "error"]
    bytes_out: int = Field(default=0, ge=0)
    error: str | None = None
```

Both are added to the `Event` discriminated union and to `__all__`. `parse_frame` gains these two branches.

## Tokenizer

`plugin/services/tokenizer.py` exposes:

```python
def count_tokens(text: str) -> int:
    """Approximate token count via tiktoken's cl100k_base encoder.

    cl100k_base is OpenAI's GPT-3.5/4 tokenizer. qwen2.5-coder and other
    supported models use different tokenizers but produce counts that
    agree within ~10–15 percent for source-code-shaped text. That is
    accurate enough for context-window budgeting; the agent loop keeps
    a safety margin (see max_total_tokens_per_turn) that absorbs the
    slop.

    The encoder is loaded lazily (first call) and cached for the
    process lifetime.
    """
```

Also:

```python
def count_messages_tokens(messages: list[dict]) -> int:
    """Sum of content tokens across an OpenAI-style message array.

    For each message: add tokens of the string content, plus a small
    fixed overhead per message for role-framing (4 tokens), plus
    recursively the tokens of any tool_calls' arguments JSON.
    """
```

Encoder: `tiktoken.get_encoding("cl100k_base")`, cached via a module-level `functools.lru_cache` on `_get_encoder()`.

Dependency: `tiktoken>=0.6`, added to `plugin.json` `python_requirements`, `plugin/requirements.txt`, `plugin/pyproject.toml`.

## Context assembler

`plugin/services/context_assembler.py`:

```python
@dataclass(frozen=True)
class AssembledContext:
    messages: list[dict]          # OpenAI-style message array ready for Ollama
    context_tokens: int           # count_messages_tokens(messages)
    repo_map_tokens: int
    rag_tokens: int
    history_tokens: int
    truncated_files: list[str]    # repo_map files dropped during trim
    dropped_turns: int            # history turns dropped during trim
    dropped_chunks: int           # rag chunks dropped during trim


async def assemble_context(
    *,
    system_prompt: str,
    tool_use_prompt: str,
    repo_map_text: str,
    rag_hits: list[SearchHit],
    history: list[dict],
    user_message: str,
    context_window: int,
    repo_map_budget: int,
    rag_budget: int,
) -> AssembledContext:
    """Build the message array within the configured budgets.

    Sections in order:
      1. system message = system_prompt
      2. system message = tool_use_prompt
      3. system message = repo_map block (trimmed to repo_map_budget)
      4. system message = rag block (top-K chunks trimmed to rag_budget)
      5. all messages from history
      6. user message = user_message

    If context_tokens exceeds context_window, drop in order:
      a. oldest history turn, repeatedly, until either (i) fits or
         (ii) only 1 history turn remains and (5) still over-budget
      b. lowest-score rag chunks (reverse order of rag_hits), repeatedly
      c. lowest-rank repo_map files (alphabetical last), repeatedly
    Sections 1, 2, and 6 are never dropped.
    """
```

`AssembledContext.context_tokens` feeds directly into `TurnStart.context_tokens` on the WebSocket.

The repo-map input is the already-rendered text from Phase 3a's `RepoMap.render(files, budget_tokens=repo_map_budget)`. The assembler trusts that value is within budget but reverifies via `count_tokens` and, if over, drops trailing blocks line-by-line (since the blocks are alphabetically ordered and already line-delimited by `===`).

The rag block is `"\n\n".join(f"=== {hit.chunk.file_path}:{hit.chunk.start_line}-{hit.chunk.end_line}\n{hit.chunk.text}" for hit in rag_hits)`, trimmed by dropping the lowest-scoring hits until under `rag_budget`.

## Agent loop

`plugin/services/agent_loop.py`:

```python
@dataclass(frozen=True)
class TurnDeps:
    ollama: OllamaClient
    tool_registry: ToolRegistry
    project: Project
    repo_map: RepoMap
    rag: RagIndex
    config: BaluCodePluginConfig
    system_prompt: str
    tool_use_prompt: str


async def run_turn(
    user_message: str,
    history: list[dict],          # mutated in place; caller owns the WS lifetime
    deps: TurnDeps,
    emit: Callable[[Event], Awaitable[None]],
) -> None:
    """Drive one user-message turn; emit WS frames via ``emit``.

    Mutates ``history`` by appending the new user message and any
    assistant/tool messages produced during the turn. Callers hold one
    history per WebSocket connection.

    Emits exactly one TurnStart, zero-or-more Token/ToolCall/ToolResult,
    and exactly one TurnEnd or Error. Never raises; all failures are
    caught and surfaced as Error + TurnEnd(stop_reason="error").
    """
```

### Algorithm

```
turn_id = new_id()
user_msg = {"role": "user", "content": user_message}
# Walk + render repo_map once per turn.
repo_map_text = await to_thread(deps.repo_map.walk_and_cache) then render(...)
rag_hits = await deps.rag.search(user_message, top_k=deps.config.rag_top_k)
history.append(user_msg)
assembled = await assemble_context(system_prompt, tool_use_prompt, repo_map_text, rag_hits,
                                   history, user_message="",  # already in history now
                                   context_window, repo_map_budget, rag_budget)
messages = assembled.messages
emit TurnStart(turn_id, model=config.chat_model, context_tokens=assembled.context_tokens)

total_tokens = assembled.context_tokens
iterations = 0
for iteration in range(config.max_iterations):
    iterations += 1
    # Stream Ollama response; collect tokens + tool_calls until we see `done`
    # OR we detect tool_calls in a frame (then break to dispatch).
    buffered_content = ""
    tool_calls = None
    async for frame in deps.ollama.chat_stream(
        config.chat_model,
        messages,
        tools=deps.tool_registry.ollama_schemas(),
        options={"temperature": config.temperature},
    ):
        message = frame.get("message") or {}
        content_piece = message.get("content") or ""
        if content_piece:
            buffered_content += content_piece
            emit Token(content=content_piece)
        frame_tool_calls = message.get("tool_calls")
        if frame_tool_calls:
            tool_calls = frame_tool_calls
            break
        if frame.get("done"):
            tool_calls = None
            break

    # Accumulate tokens; enforce per-turn total.
    total_tokens += count_tokens(buffered_content)
    if total_tokens > config.max_total_tokens_per_turn:
        emit TurnEnd(turn_id, total_tokens, iterations, stop_reason="max_iter")
        history.append({"role": "assistant", "content": buffered_content})
        return

    if not tool_calls:
        # Clean completion
        history.append({"role": "assistant", "content": buffered_content})
        emit TurnEnd(turn_id, total_tokens, iterations, stop_reason="done")
        return

    # Otherwise, dispatch tool calls
    history.append({"role": "assistant", "content": buffered_content, "tool_calls": tool_calls})
    messages = history  # history IS the message list; they share references

    for call in tool_calls:
        name = call["function"]["name"]
        raw_args = call["function"]["arguments"]
        args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
        tc_id = f"tc_{iterations}_{uuid4().hex[:6]}"
        try:
            tool = deps.tool_registry.get(name)
            parsed = tool.args_schema.model_validate(args)
        except (KeyError, ValidationError) as exc:
            emit ToolCall(tc_id, tool=name, args=args, auto_approved=True)
            emit ToolResult(tc_id, status="error", bytes_out=0, error=str(exc))
            history.append({"role": "tool", "name": name,
                            "content": f"error: {exc}"})
            continue

        emit ToolCall(tc_id, tool=name, args=args, auto_approved=True)
        try:
            result = await tool.execute(parsed, make_ctx(deps, turn_id))
        except Exception as exc:
            emit ToolResult(tc_id, status="error", bytes_out=0, error=str(exc))
            history.append({"role": "tool", "name": name,
                            "content": f"error: {exc}"})
            continue
        emit ToolResult(tc_id, status=result.status, bytes_out=result.bytes_out,
                        error=result.error)
        history.append({"role": "tool", "name": name, "content": result.text})

# Iteration cap hit
emit TurnEnd(turn_id, total_tokens, iterations, stop_reason="max_iter")
```

### Error handling

Any unhandled exception inside `run_turn` (Ollama unreachable, tokenizer bug, etc.) is caught by an outer `try/except` in the WS handler and converted to `Error(code, message)` followed by `TurnEnd(stop_reason="error")`. The turn's history mutations are rolled back (the final assistant/tool messages are not appended on the error path) so the next turn doesn't see malformed context.

Specifically: `OllamaUnreachable` → `Error(code="ollama_unreachable", message=str(exc))`, `OllamaTimeoutError` → `Error(code="ollama_timeout", ...)`, anything else → `Error(code="internal", message="<class_name>: <exc>")`.

## Tool protocol and registry

### `plugin/services/tools/base.py`

```python
@dataclass(frozen=True)
class ToolContext:
    project_root: Path
    project_id: int
    turn_id: str


@dataclass(frozen=True)
class ToolResult:
    status: Literal["ok", "error"]
    text: str                 # the message the model sees as the tool's output
    bytes_out: int = 0        # raw byte size of the tool's production (for the WS event)
    error: str | None = None


class Tool(Protocol):
    name: str
    description: str
    args_schema: type[BaseModel]
    risk: Literal["read", "write", "exec", "network"]

    async def execute(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...
```

### `plugin/services/tools/__init__.py`

```python
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None: ...
    def get(self, name: str) -> Tool: ...     # raises KeyError
    def names(self) -> list[str]: ...
    def ollama_schemas(self) -> list[dict]:
        """Convert each registered tool to Ollama's tool-schema format:
        {"type": "function", "function": {"name": ..., "description": ...,
         "parameters": <JSON Schema from args_schema.model_json_schema()>}}
        """
```

A module-level function `default_registry()` returns a `ToolRegistry` pre-registered with the three v1 read-only tools.

### Three tools

**`read_file`** — `args_schema` fields:
- `path: str` (required, min_length=1) — relative to project root.
- `max_bytes: int = 2_097_152` (default 2 MB, bounded 1 ≤ … ≤ 10 MB).

Behavior: `(ctx.project_root / args.path).resolve()`, reject if not `is_relative_to(ctx.project_root.resolve())` with `ToolResult(status="error", error="path escapes project root")`. Reject symlinks escaping the root (realpath check). Read up to `max_bytes` bytes; detect binary via `\x00` in the first 1024 bytes and reject with `"binary file not readable"`. Decode UTF-8 with `errors="replace"`. Return the text as `ToolResult(status="ok", text=<bytes decoded>, bytes_out=len(bytes))`.

**`glob`** — `args_schema` fields:
- `pattern: str` (required, min_length=1) — POSIX-style glob relative to project root.

Behavior: `Path(project_root).glob(pattern)` (NOT `rglob` — user controls `**`). Filter out paths whose ancestors include any `IGNORE_DIRS`. Truncate at 1000 results. Return newline-joined relative POSIX paths. `bytes_out = len(text)`.

**`grep`** — `args_schema` fields:
- `pattern: str` (required, min_length=1) — Python regex.
- `glob: str | None = None` — optional path filter, same semantics as `glob` tool.
- `case_insensitive: bool = False`.

Behavior: Prefer `rg` (ripgrep) subprocess if on PATH — `rg --line-number --no-heading --color=never -e <pattern> [-i] [-g <glob>] <project_root>`. On any invocation failure or missing binary, fall back to pure-Python: enumerate files (same ignore filter), read each (up to 2 MB), `re.finditer`. Max 500 matches across all files. Return `path:line:content` lines separated by `\n`.

### Instantiated tools as plugin-wide singletons

Stateless; no need to construct fresh per-turn. `BaluCodePlugin.on_startup` calls `default_registry()` and stashes it; the WS handler reads it via a new `deps.get_tool_registry` getter.

**Note to implementer:** `deps.py` gains TWO new singletons in Phase 4a: `_tool_registry: ToolRegistry | None` and `_plugin_config: BaluCodePluginConfig | None`. `set_singletons` grows from 4 to 6 params (store, ollama, rag_registry, index_job_tracker, tool_registry, plugin_config). `BaluCodePlugin.on_startup` constructs both new singletons (`default_registry()` for the tool registry; `self._config` for the plugin config) and passes them into `set_singletons`. `BaluCodePlugin.on_shutdown` includes them in the null-check guard and clears them via `clear_singletons()`. Two new accessors — `get_tool_registry()` and `get_plugin_config()` — raise `RuntimeError` when called before startup, matching the pattern of the existing four.

## Prompts

### `plugin/prompts/system.md`

A single ~800-token prompt establishing the agent's identity, priorities, and core behaviour rules. Plain markdown, no placeholders. Key points:

- You are Balu Code, a self-hosted coding agent running against a local Ollama.
- You have access to a repository map and semantic search results in your context.
- Before answering, determine whether you need to read actual source; if yes, call `read_file`.
- Prefer surgical edits to large rewrites.
- Never fabricate code that isn't in the retrieved context.
- If the retrieved context is insufficient, use `glob` or `grep` to find more.

### `plugin/prompts/tool_use.md`

A single ~400-token prompt giving concrete tool-calling guidance. Key points:

- You have three tools: `read_file`, `glob`, `grep`. (In Phase 4b this expands.)
- Call at most one tool per turn when possible; batch related reads when helpful.
- When the user asks about a specific file, read it before speculating.
- If a `tool_result` contains `status: "error"`, explain the failure to the user or try a different approach; don't retry blindly.

Both files are loaded once at plugin import time (module-level constants in `agent_loop.py`) via `(Path(__file__).parent.parent / "prompts" / "system.md").read_text()`.

## Config additions

`plugin/config.py`'s `BaluCodePluginConfig` gains seven fields matching the parent design spec:

```python
context_window: int = 32768
repo_map_budget: int = 6144
rag_budget: int = 4096
rag_top_k: int = 8
max_iterations: int = 12
max_total_tokens_per_turn: int = 80000
temperature: float = Field(default=0.2, ge=0.0, le=2.0)
```

`get_default_config()` surfaces them automatically; the existing `model_config = ConfigDict(extra="forbid")` test already covers rejection of unknown fields.

## Route

`plugin/routes.py` gains one WebSocket route inside `build_router()`:

```python
@router.websocket("/chat")
async def chat_socket(
    websocket: WebSocket,
    project_id: int,
    _user: UserPublic = Depends(get_current_user),
    store: ProjectStore = Depends(get_project_store),
    ollama: OllamaClient = Depends(get_ollama_client),
    rag_registry: RagRegistry = Depends(get_rag_registry),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    config: BaluCodePluginConfig = Depends(get_plugin_config),
) -> None:
    """Streaming chat endpoint.

    Accepts UserMessage frames, runs a turn per frame, emits TurnStart
    / Token / ToolCall / ToolResult / TurnEnd / Error frames. Maintains
    connection-scoped history.
    """
```

`project_id` is a required query parameter. The handler:

1. Resolves the project via `store.get_project(project_id)` → 4xx close (code 1008) on `ProjectNotFoundError`.
2. Opens the project's `RagIndex` via `rag_registry.get(project_id)` → 4xx close on `RagIndexUnavailable`.
3. Constructs a `RepoMap` for the project.
4. `await websocket.accept()`.
5. Builds `TurnDeps` + empty `history: list[dict] = []` + `emit = lambda ev: websocket.send_json(ev.model_dump())`.
6. In an infinite loop: `raw = await websocket.receive_json()` → `parse_frame(raw)` → dispatch.
   - `UserMessage` → `await run_turn(content, history, deps, emit)`.
   - Any other type in 4a: emit `Error(code="unsupported_frame", ...)` and continue (the connection stays open; Phase 4b adds approval/cancel).
   - `ValidationError` on parse → emit `Error(code="bad_frame", ...)` and continue.
7. On `WebSocketDisconnect`: clean exit; history is discarded.

## Test strategy

Target: ~32 new tests. Total suite ≥226 after Phase 4a.

- **`test_tokenizer.py`** (~3) — `count_tokens("")` returns 0; `count_tokens("hello world")` returns a small positive int; `count_messages_tokens([{role,content}*3])` is roughly the sum of contents plus per-message overhead.
- **`test_context_assembler.py`** (~6) — happy path message order; oversized history drops oldest turn first; oversized with short history drops lowest-score RAG chunks; catastrophic oversize drops repo-map blocks; system/tool_use/user never dropped; `context_tokens` matches `count_messages_tokens(messages)`.
- **`test_tool_base.py`** (~4) — `ToolRegistry.register`/`get`/`names`; `ollama_schemas()` produces the `function.parameters` JSON schema for a sample tool; duplicate registration raises.
- **`test_tool_read_file.py`** (~5) — happy path reads UTF-8 content; path-escape via `../../etc/passwd` returns error; symlink escape returns error; binary file (null byte) returns error; oversized file truncated to `max_bytes`.
- **`test_tool_glob.py`** (~4) — pattern match with tmp_path fixture; `IGNORE_DIRS` exclusion; 1000-result truncation; zero matches returns empty-string text + `status="ok"`.
- **`test_tool_grep.py`** (~4) — regex match against fixture files; 500-match truncation; `glob` parameter filters; missing-ripgrep fallback still matches correctly.
- **`test_agent_loop.py`** (~5) — FakeOllama yields `(token, token, done)` → `TurnEnd(stop_reason="done")`; `(tool_call, done)` → dispatches tool, appends tool result, second iteration; iteration cap hit → `stop_reason="max_iter"`; Ollama raises → emits `Error` + `TurnEnd("error")`; tool raises → `ToolResult(status="error")` + loop continues.
- **`test_routes_chat.py`** (~5) — `TestClient.websocket_connect` happy path (send `UserMessage`, receive `TurnStart` + tokens + `TurnEnd`); multi-turn on same connection keeps history; 401 close on `dependency_overrides` raising `HTTPException(401)`; 4xx close on unknown project_id; unsupported-frame yields `Error` and connection stays open.
- **`test_events.py`** (extended in `shared/`, ~2) — `ToolCall` round-trip + discriminator; `ToolResult` round-trip + `status` literal rejection.

## FakeOllama for tests

`test_agent_loop.py` and `test_routes_chat.py` share a scripted `_FakeOllama`:

```python
class _FakeOllama:
    def __init__(self, scripted_frames: list[list[dict]]) -> None:
        """Each outer list entry is the frame stream for one chat_stream call."""
        self._calls = iter(scripted_frames)

    async def chat_stream(self, model, messages, tools=None, options=None):
        frames = next(self._calls)
        for f in frames:
            yield f

    async def close(self) -> None: pass
    async def list_models(self): return []
    async def embed(self, model, texts): return [[0.0] * 768 for _ in texts]
```

Pre-canned frame streams cover: (done-only), (token × N + done), (token + tool_call + done), mixed.

## Dependencies

| Package | Purpose | Size |
|---|---|---|
| `tiktoken>=0.6` | Accurate token counts for prompt budgeting. | ~3 MB |

Added to `plugin.json` `python_requirements`, `plugin/requirements.txt`, `plugin/pyproject.toml`.

## Definition of Done

- ~32 new tests pass locally; full suite ≥226.
- CI green on Python 3.11 + 3.12.
- `ruff check .` / `ruff format --check .` clean.
- `.bhplugin` archive contains `services/tokenizer.py`, `services/context_assembler.py`, `services/agent_loop.py`, all of `services/tools/`, and both `prompts/*.md` files.
- Scripted FakeOllama happy path: `WS /chat` receives a `user_message`, emits `turn_start` → at least one `token` → `turn_end(stop_reason="done")`.
- Tool happy path: a `user_message` that should trigger `read_file` causes the loop to emit `tool_call` + `tool_result` before the final `turn_end`.

## Carryovers into Phase 4b

- Extract `read_file`'s inline path-containment check into a shared helper (`plugin/services/paths.py`) before `write_file`/`apply_patch` land.
- Introduce `approval_request` / `approval` / `cancel` WS frames + `stop_reason="cancelled"`.
- Add the four write/exec/network tools.
- Wire `audit_log` emission for every tool call (read tools too — v1 logs even auto-approved).
- Add `StartTurn` / `history` priming frame so CLI's `session resume` works (Phase 5).

## What Phase 5 (CLI) will build on top

- The WS envelopes are stable after this phase (modulo the four Phase-4b frames).
- `connection-scoped history` means session resume needs either a reconnect-with-replay pattern (CLI sends prior user_messages in a loop before the new one — slow and wasteful because Ollama re-generates) or the history-priming frame added in 4b / 5. Decision: add the priming frame in 4b.
- `context_tokens` in `TurnStart` gives the CLI something to render as "context size" before the first token arrives.
