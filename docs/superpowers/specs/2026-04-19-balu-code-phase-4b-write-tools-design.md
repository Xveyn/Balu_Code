# Balu Code — Phase 4b Design (Write Tools + Approval + Cancel + Audit)

**Status:** draft, user-approved
**Date:** 2026-04-19
**Depends on:** Phase 4a (read-only agent loop + WS `/chat`) shipped on `main`

## §1 — Architecture & Scope

Phase 4b adds **write-side tools, an approval gate, turn cancellation, and an audit-log integration** on top of the Phase 4a read-only agent loop. No new top-level service — every extension hangs off modules that already exist (`run_turn`, `/chat` handler, `ToolRegistry`, `deps.py`).

**New surface area:**
- 4 tools: `write_file` (risk=`write`), `apply_patch` (risk=`write`), `run_bash` (risk=`exec`), `web_fetch` (risk=`network`)
- 3 new WS envelopes: `ApprovalRequest`, `Approval`, `Cancel`
- Approval state machine in `run_turn` + per-connection pending-approval dispatch in `/chat` handler
- Hybrid cancel token (soft between Ollama chunks + between tool calls; hard subprocess-kill for `run_bash`)
- Audit log integration reusing BaluHost's existing `audit_log` table (`source="balu_code"`)

**Approval model** (decided during brainstorming):
- **Server-dumb, client-smart.** Server emits `ApprovalRequest` for every tool whose `risk != "read"`. Client decides auto-vs-prompt (via `--yolo`, `.balucode.yaml`, or interactive prompt) and replies with `Approval(approved=bool)`.
- Defaults baked into the client (reference, not server policy): `auto_approve=[read_file, glob, grep]`, `allow_write=false`, `allow_bash=false`, `allow_web_fetch=true`, `--yolo` overrides all.

**Rejection handling:** a client `Approval(approved=False)` produces a `ToolResult(status="error", error="user rejected: <reason>")` that is fed back into the model as a tool turn. The loop continues, so the model can adapt ("should I edit foo.py instead?"). No new stop reason needed.

**Cancel semantics:** `Cancel` frame flips a token. The loop checks it between Ollama stream chunks, before each tool dispatch, and while awaiting approval. `run_bash` additionally kills the subprocess hard (SIGTERM, 2s grace, SIGKILL). Other in-flight tool calls run to completion (they're fast).

**Audit target:** BaluHost's existing `audit_log` table via `app.services.audit.logger_db`, with `source="balu_code"`. Records appear in the existing BaluHost Audit page with no extra UI work.

**Out of scope for 4b:**
- CLI-side approval UX (Textual TUI with diff viewer) — deferred to Phase 5.
- `.balucode.yaml` parser — deferred to Phase 5; no per-project server-side policy in 4b.
- Smart ranker for repo-map (3b carryover) — still waiting for CLI to emit `opened_files` hints.

## §2 — Protocol Extensions

Three new envelopes in `shared/src/balu_code_shared/events.py`. `StopReason` adds `"max_tokens"` (a 4a carryover — the existing `max_total_tokens_per_turn` trip currently collides with the iteration-cap case). `"cancelled"` is already present from 4a.

```python
class ApprovalRequest(_FrozenBase):
    type: Literal["approval_request"] = "approval_request"
    tool_call_id: str = Field(..., min_length=1)
    tool: str = Field(..., min_length=1)
    args: dict[str, Any]
    risk: Literal["write", "exec", "network"]

class Approval(_FrozenBase):
    type: Literal["approval"] = "approval"
    tool_call_id: str = Field(..., min_length=1)
    approved: bool
    reason: str | None = None

class Cancel(_FrozenBase):
    type: Literal["cancel"] = "cancel"
    turn_id: str = Field(..., min_length=1)
```

`Event` union, `parse_frame`, and `__all__` are extended accordingly.

**Flow:**
```
server → ToolCall(auto_approved=False)   # announces the planned invocation
server → ApprovalRequest                  # blocks loop, awaits decision
client → Approval(approved=True|False, reason?)
server → ToolResult(...)                  # approved: normal execution
server → ToolResult(status="error",       # rejected: fed back into the model
                    error="user rejected: <reason>")
```

**Design rationale:**
- `risk` is server-side truth, duplicated into the envelope — the client may be on an older version and must not be the source of risk classification.
- `args` is duplicated from the original `ToolCall` on purpose: the client would otherwise need to maintain its own `tool_call_id → args` map just to render the approval prompt.
- `Cancel.turn_id` is scoped, not global — prevents a late Cancel from killing a freshly-started next turn.
- No `"rejected"` stop reason: rejection feeds back into the model as a tool result and the loop ends normally (`"done"` or `"max_iter"` or `"max_tokens"`).

## §3 — Tool Specs

All four tools live in `plugin/tools/` and implement the existing `Tool` protocol from Phase 4a (`name`, `description`, `risk`, `args_schema`, `execute`). Path-containment for every filesystem tool goes through a new single-source-of-truth helper.

### `write_file` (risk=`write`)

```python
class WriteFileArgs(BaseModel):
    path: str           # project-relative
    content: str
    create_dirs: bool = False
```

- Path-containment via `plugin/services/paths.resolve_within_project`.
- Overwrite allowed. Requiring a separate check-exists tool would force two-step model behaviour for a common operation.
- Max 2 MB content.
- UTF-8, `newline=""` (no line-ending magic).
- Returns: `{"status": "ok", "bytes_written": N, "created": bool}`.

### `apply_patch` (risk=`write`)

```python
class ApplyPatchArgs(BaseModel):
    diff: str  # unified-diff format
```

- Parser: `unidiff` package (pure Python; no git subprocess).
- Multi-file patches OK. Each hunk is validated against the current file content; **fail-fast** on the first mismatch — no partial applies.
- Path-containment per target file.
- `--- /dev/null` → create; `+++ /dev/null` → delete.
- Returns: `{"status": "ok", "files_changed": [...], "hunks_applied": N}`.

### `run_bash` (risk=`exec`)

```python
class RunBashArgs(BaseModel):
    command: str
    timeout_s: int = 60  # clamped to 1..300
```

- `asyncio.create_subprocess_shell`, `cwd=project_root`, `shell=/bin/bash`.
- Env inherited minus any `BALUHOST_*` keys; `PATH` pinned to `/usr/local/bin:/usr/bin:/bin`.
- Combined stdout+stderr, max 256 KB tail (head+tail on overflow).
- Cancel hook: `process.terminate()` → 2 s grace → `process.kill()`.
- Returns: `{"status": "ok"|"error", "exit_code": N, "output": "..."}`.

### `web_fetch` (risk=`network`)

```python
class WebFetchArgs(BaseModel):
    url: HttpUrl
    max_bytes: int = 500_000  # clamped to 1 KB..2 MB
```

- `httpx.AsyncClient`, timeout 20 s, `follow_redirects=True`, max 5 redirects.
- **SSRF guard**: resolve DNS before fetching; block RFC1918 ranges, `127.0.0.0/8`, `::1`, and `169.254.0.0/16`.
- HTML → extracted via `trafilatura.extract` (Readability-style). Other content types → raw bytes up to `max_bytes`.
- Returns: `{"status": "ok", "url_final": "...", "content_type": "...", "content": "..."}`.

### New service: `plugin/services/paths.py`

Exposes `resolve_within_project(project_root: Path, rel_path: str) -> Path`. Single source of truth for path containment — rejects absolute paths, `..` traversal, and symlink-escapes. `read_file.py` is migrated to use this (4a carryover resolved).

## §4 — `run_turn` Changes

Three new responsibilities for the existing loop in `plugin/services/run_turn.py`.

### A. Approval gate

Every `ToolCall` the model emits goes through:

```python
auto_approved = tool.risk == "read"
await send(ToolCall(..., auto_approved=auto_approved))

if not auto_approved:
    await send(ApprovalRequest(tool_call_id, tool, args, risk))
    decision = await _wait_for_approval(tool_call_id, cancel_token)
    if not decision.approved:
        tool_result = ToolResult(
            tool_call_id=tool_call_id,
            status="error",
            error=f"user rejected: {decision.reason or 'no reason'}",
        )
        await send(tool_result)
        messages.append({"role": "tool", ...})  # feed into history, loop continues
        continue

result = await tool.execute(args, cancel_token)
```

`_wait_for_approval` is backed by an `asyncio.Future` keyed on `tool_call_id`. The future is placed in the per-connection `pending_approvals` dict; the WS handler resolves it when the matching `Approval` frame arrives.

### B. Cancel token (hybrid)

```python
class CancelToken:
    def __init__(self):
        self._event = asyncio.Event()
    def cancel(self): self._event.set()
    @property
    def cancelled(self) -> bool: return self._event.is_set()
    def check(self):
        if self._event.is_set():
            raise asyncio.CancelledError("cancelled by user")
    async def wait(self) -> None:
        await self._event.wait()
```

Check points:

1. Between Ollama stream chunks (soft): `cancel_token.check()` inside `async for chunk in ollama_stream`.
2. Before each tool dispatch.
3. While awaiting approval: the handler's `Cancel` branch both flips the token and `.cancel()`s every pending approval future, so the awaiter raises `CancelledError` automatically — no extra wait-composition in `run_turn`.
4. Inside `run_bash.execute` (hard): a watcher task `await cancel_token.wait()` and kills the subprocess when the event fires.

The handler calls `cancel_token.cancel()` on incoming `Cancel`. `CancelledError` propagates up, is caught at the top of `run_turn`, and produces `TurnEnd(stop_reason="cancelled")`.

### C. Audit hook

After every `ToolResult` (ok, error, or rejected):

```python
await audit_log.record(
    source="balu_code",
    action=f"tool:{tool_name}",
    user_id=connection.user_id,
    metadata={
        "turn_id": turn_id,
        "tool_call_id": tool_call_id,
        "args": args,
        "status": result.status,
        "bytes_out": result.bytes_out,
        "error": result.error,
        "approved": auto_approved or (decision and decision.approved),
        "auto_approved": auto_approved,
    },
)
```

Injected via `deps.py` as a new singleton `AuditLogger` wrapping `app.services.audit.logger_db`.

### D. Tool protocol extension

```python
async def execute(self, args: BaseModel, cancel_token: CancelToken) -> ToolResult: ...
```

Existing 4a tools (`read_file`, `glob`, `grep`) simply ignore the token — they're fast enough that mid-flight cancellation isn't needed. Only `run_bash` uses it actively.

### E. 4a carryovers resolved here

- `StopReason` gets `"max_tokens"`; the `max_total_tokens_per_turn` trip now maps to that (no more collision with `"max_iter"`).
- Context tokens: `total_tokens += count_messages_tokens(messages)` runs at the top of every iteration instead of only at `TurnStart`.

## §5 — WS `/chat` Handler Changes

`plugin/routes/chat.py` gains approval + cancel routing alongside the existing `UserMessage` dispatch.

### Per-connection state

```python
pending_approvals: dict[str, asyncio.Future[Approval]] = {}
current_turn: CancelToken | None = None
current_turn_id: str | None = None
```

All three span the WS connection lifetime. `pending_approvals` is explicitly cleared after each `TurnEnd`, and `current_turn` / `current_turn_id` are reset to `None`. `current_turn_id` is the UUID emitted in `TurnStart`; the handler stores it so a `Cancel` frame can be matched against the live turn.

### Receive-loop dispatch

```python
while True:
    frame = await ws.receive_json()
    event = parse_frame(frame)

    match event:
        case UserMessage():
            if current_turn is not None:
                await send(Error(code="turn_in_flight", message="..."))
                continue
            current_turn = CancelToken()
            current_turn_id = str(uuid4())
            try:
                await run_turn(
                    turn_id=current_turn_id,
                    user_message=event,
                    messages=history,
                    registry=registry,
                    send=send,
                    cancel_token=current_turn,
                    pending_approvals=pending_approvals,
                    audit_log=audit_log,
                    user_id=user_id,
                )
            finally:
                current_turn = None
                current_turn_id = None
                pending_approvals.clear()

        case Approval():
            fut = pending_approvals.pop(event.tool_call_id, None)
            if fut is None:
                await send(Error(code="unknown_approval",
                                 message=f"no pending request for {event.tool_call_id}"))
            elif not fut.done():
                fut.set_result(event)

        case Cancel():
            if current_turn is None or event.turn_id != current_turn_id:
                await send(Error(code="no_turn_to_cancel", message="..."))
            else:
                current_turn.cancel()
                for fut in pending_approvals.values():
                    if not fut.done():
                        fut.cancel()

        case _:
            await send(Error(code="unexpected_frame",
                             message=f"got {event.type} from client"))
```

### `run_turn` signature

```python
async def run_turn(
    *,
    turn_id: str,
    user_message: UserMessage,
    messages: list[dict],
    registry: ToolRegistry,
    send: Callable[[Event], Awaitable[None]],
    cancel_token: CancelToken,
    pending_approvals: dict[str, asyncio.Future[Approval]],
    audit_log: AuditLogger,
    user_id: int,
) -> None: ...
```

`turn_id` is generated by the handler (not by `run_turn`), because the handler needs it for `Cancel`-frame matching before `run_turn` would have produced it. `run_turn` emits it verbatim in `TurnStart` and `TurnEnd`.

`run_turn` inserts futures into `pending_approvals`; the handler pops them out when matching `Approval` frames arrive. This is the only cross-task communication channel.

### Error boundary

- `CancelledError` from `run_turn`: `TurnEnd(stop_reason="cancelled")` was already emitted; no extra Error frame.
- Any other exception: `Error(code="turn_failed", message=str(e))` + `TurnEnd(stop_reason="error")`. Connection stays open (consistent with 4a).

## §6 — Tests & Rollout

### New tests

**Tool level** (`plugin/tests/test_tools_*.py`):
- `test_tools_write_file.py` — happy path, overwrite, `create_dirs`, path traversal blocked, size cap, UTF-8 edge cases.
- `test_tools_apply_patch.py` — single-hunk, multi-file, create-from-`/dev/null`, delete-to-`/dev/null`, mismatch fails fast (no partial), path-containment.
- `test_tools_run_bash.py` — exit 0, exit non-zero, timeout, stdout+stderr merge, output tail-truncation, cancel-token kills subprocess.
- `test_tools_web_fetch.py` — HTML extraction via trafilatura (offline fixture), redirect cap, `max_bytes`, SSRF block (RFC1918 + loopback + link-local).

**Service level:**
- `test_paths.py` — `resolve_within_project` happy path, `..` traversal, symlink escape, absolute path reject.

**Approval / cancel flow** (extend `plugin/tests/test_routes_chat.py`):
- `test_chat_approval_approved` — `write_file` ToolCall → `ApprovalRequest` → `Approval(True)` → `ToolResult(ok)`.
- `test_chat_approval_rejected` — `Approval(False)` → `ToolResult(error="user rejected: ...")` → loop continues (not `TurnEnd`).
- `test_chat_cancel_between_tools` — `Cancel` mid-turn → subprocess killed (`run_bash`), `TurnEnd(cancelled)`.
- `test_chat_unknown_approval` → `Error(code="unknown_approval")`.
- `test_chat_cancel_wrong_turn_id` → `Error(code="no_turn_to_cancel")`.

**Audit:**
- `test_audit_tool_call` — `FakeAuditLogger` captures `record()` calls; assert every `ToolResult` produces exactly one audit record with the expected fields.
- `test_audit_rejection_recorded` — rejected tool calls land in audit with `approved=False`.

**Run-turn:**
- `test_run_turn_cancelled` — `CancelToken.cancel()` from fake task → `CancelledError` → `TurnEnd(cancelled)`.
- `test_run_turn_max_tokens` — synthetic budget cap → `TurnEnd(max_tokens)` (the 4a carryover).

Target: ~290 tests total (248 today + ~40 new).

### New dependencies

- `unidiff>=0.7` (`apply_patch`).
- `httpx>=0.27` (`web_fetch` — currently transitive via Ollama client, made explicit).
- `trafilatura>=1.12` (HTML extraction in `web_fetch`).

All added to `plugin/pyproject.toml` and `plugin/requirements.txt`.

### Rollout — task shape for `writing-plans`

1. Shared events: `ApprovalRequest`, `Approval`, `Cancel` + `StopReason` extension (adds `"max_tokens"`).
2. `plugin/services/paths.py` + migrate `read_file.py` to it.
3. `CancelToken` service.
4. Tool `write_file`.
5. Tool `apply_patch`.
6. Tool `run_bash`.
7. Tool `web_fetch`.
8. `AuditLogger` wrapper + `deps.py` wiring.
9. `run_turn`: approval-gate + audit-hook + token re-accumulation.
10. `run_turn`: cancel-token integration.
11. WS handler: `pending_approvals` + `Cancel`/`Approval` routing.
12. End-to-end tests for approval flow.
13. End-to-end tests for cancel flow.
14. `default_registry()` extended to include the four new tools.
15. CI green + Phase-4b verification checklist.

### Out of scope (restated)

- CLI-side approval UX (Textual TUI + diff viewer) → Phase 5.
- `.balucode.yaml` parser → Phase 5.
- Smart ranker for repo-map (3b carryover) → waits for CLI `opened_files` hints.
