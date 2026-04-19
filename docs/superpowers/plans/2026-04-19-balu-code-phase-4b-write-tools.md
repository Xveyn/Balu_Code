# Balu Code — Phase 4b: Write Tools + Approval + Cancel + Audit

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add write-side agent capability — `write_file`, `apply_patch`, `run_bash`, `web_fetch` — gated by a server-dumb/client-smart approval flow, with turn cancellation and audit-log integration. After 4b the agent can actually modify a repo, not just read it.

**Architecture:** Three new WS envelopes (`ApprovalRequest`, `Approval`, `Cancel`) extend the shared protocol. Server emits `ApprovalRequest` for any tool with `risk != "read"`; the client decides auto-vs-prompt and replies with `Approval(approved=bool)`. Rejection is fed back into the model as `ToolResult(status="error")` so the loop continues. Cancel flips an `asyncio.Event`-backed `CancelToken` that the loop checks between Ollama chunks and tool calls (soft) and that `run_bash` watches to kill its subprocess (hard). Every tool invocation is written to BaluHost's existing `audit_log` table via `app.services.audit.logger_db.AuditLoggerDB` with `event_type="BALU_CODE"`.

**Tech Stack:** Python 3.11+, FastAPI WebSockets, Pydantic v2, `unidiff>=0.7`, `trafilatura>=1.12`, existing `httpx`+`tiktoken`+`tree-sitter` stack, BaluHost's `AuditLoggerDB`.

**Parent spec:** [`docs/superpowers/specs/2026-04-19-balu-code-phase-4b-write-tools-design.md`](../specs/2026-04-19-balu-code-phase-4b-write-tools-design.md)

---

## File Structure (this phase)

```
Balu_Code/
├── plugin/
│   ├── plugin.json                            [mod (Task 1)]
│   ├── requirements.txt                       [mod (Task 1)]
│   ├── pyproject.toml                         [mod (Task 1)]
│   ├── deps.py                                [mod (Task 9)]
│   ├── __init__.py                            [mod (Task 9)]
│   ├── routes.py                              [mod (Task 12)]
│   ├── services/
│   │   ├── paths.py                           [new (Task 3)]
│   │   ├── cancel.py                          [new (Task 4)]
│   │   ├── audit.py                           [new (Task 9)]
│   │   ├── agent_loop.py                      [mod (Tasks 10, 11)]
│   │   └── tools/
│   │       ├── __init__.py                    [mod (Task 13)]
│   │       ├── base.py                        [mod (Task 4)]
│   │       ├── read_file.py                   [mod (Task 3)]
│   │       ├── write_file.py                  [new (Task 5)]
│   │       ├── apply_patch.py                 [new (Task 6)]
│   │       ├── run_bash.py                    [new (Task 7)]
│   │       └── web_fetch.py                   [new (Task 8)]
│   └── tests/
│       ├── test_paths.py                      [new (Task 3)]
│       ├── test_cancel.py                     [new (Task 4)]
│       ├── test_audit.py                      [new (Task 9)]
│       ├── test_tool_base.py                  [mod (Task 4)]
│       ├── test_tool_read_file.py             [mod (Task 3)]
│       ├── test_tool_write_file.py            [new (Task 5)]
│       ├── test_tool_apply_patch.py           [new (Task 6)]
│       ├── test_tool_run_bash.py              [new (Task 7)]
│       ├── test_tool_web_fetch.py             [new (Task 8)]
│       ├── test_tool_glob.py                  [mod (Task 4)]
│       ├── test_tool_grep.py                  [mod (Task 4)]
│       ├── test_agent_loop.py                 [mod (Tasks 10, 11)]
│       ├── test_routes_chat.py                [mod (Tasks 12, 14)]
│       └── test_plugin_lifecycle.py           [mod (Task 9)]
└── shared/
    ├── src/balu_code_shared/events.py         [mod (Task 2)]
    └── tests/test_events.py                   [mod (Task 2)]
```

Task 15 is end-of-phase verification.

---

## Task 1: Add `unidiff` and `trafilatura` dependencies

`httpx` is already present (pinned in Phase 2 for the Ollama client). `unidiff` is the patch-parser for `apply_patch`; `trafilatura` does Readability-style HTML extraction in `web_fetch`.

**Files:**
- Modify: `plugin/plugin.json`
- Modify: `plugin/requirements.txt`
- Modify: `plugin/pyproject.toml`

- [ ] **Step 1: Update `plugin/plugin.json`** — extend `python_requirements` (alphabetical):

Current:
```json
  "python_requirements": [
    "httpx>=0.27",
    "pydantic>=2.6",
    "sqlite-vec>=0.1.9",
    "tiktoken>=0.6",
    "tree-sitter>=0.22",
    "tree-sitter-python>=0.21"
  ],
```

Replace with:
```json
  "python_requirements": [
    "httpx>=0.27",
    "pydantic>=2.6",
    "sqlite-vec>=0.1.9",
    "tiktoken>=0.6",
    "trafilatura>=1.12",
    "tree-sitter>=0.22",
    "tree-sitter-python>=0.21",
    "unidiff>=0.7"
  ],
```

- [ ] **Step 2: Update `plugin/requirements.txt`** — alphabetical:

```
httpx>=0.27
pydantic>=2.6
sqlite-vec>=0.1.9
tiktoken>=0.6
trafilatura>=1.12
tree-sitter>=0.22
tree-sitter-python>=0.21
unidiff>=0.7
```

- [ ] **Step 3: Update `plugin/pyproject.toml`** — extend `[project] dependencies`:

```toml
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.6",
  "sqlite-vec>=0.1.9",
  "tiktoken>=0.6",
  "trafilatura>=1.12",
  "tree-sitter>=0.22",
  "tree-sitter-python>=0.21",
  "unidiff>=0.7",
  "fastapi>=0.110",
  "balu-code-shared",
]
```

- [ ] **Step 4: Install dev deps + smoke-test both libs**

```bash
source .venv/bin/activate
pip install -e "plugin[dev]"
python -c "
import unidiff, trafilatura
print('unidiff', unidiff.__version__)
print('trafilatura', trafilatura.__version__)
ps = unidiff.PatchSet.from_string('--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n')
assert len(ps) == 1
html = '<html><body><p>hello world</p></body></html>'
assert 'hello world' in (trafilatura.extract(html) or '')
print('smoke ok')
"
```
Expected: version lines + `smoke ok`.

- [ ] **Step 5: Run existing suite — no regression**

```bash
ruff check .
pytest -q
```
Expected: 248 passed, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add plugin/plugin.json plugin/requirements.txt plugin/pyproject.toml
git commit -m "build(plugin): add unidiff + trafilatura dependencies"
```

---

## Task 2: Extend shared events — `ApprovalRequest`, `Approval`, `Cancel`, `max_tokens` stop-reason

Three new envelopes + one new `StopReason` literal variant (`"max_tokens"`). `"cancelled"` and the four other stop reasons already exist from 4a.

**Files:**
- Modify: `shared/src/balu_code_shared/events.py`
- Modify: `shared/tests/test_events.py`

- [ ] **Step 1: Write the failing tests**

Append to `shared/tests/test_events.py` (before the final `test_event_union_includes_all_seven` — we will rewrite that too):

```python
class TestApprovalRequest:
    def test_constructs_with_all_fields(self):
        from balu_code_shared.events import ApprovalRequest

        evt = ApprovalRequest(
            tool_call_id="tc_1",
            tool="write_file",
            args={"path": "foo.py", "content": "x"},
            risk="write",
        )
        assert evt.type == "approval_request"
        assert evt.tool_call_id == "tc_1"
        assert evt.tool == "write_file"
        assert evt.args == {"path": "foo.py", "content": "x"}
        assert evt.risk == "write"

    def test_rejects_empty_tool_call_id(self):
        import pytest
        from balu_code_shared.events import ApprovalRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ApprovalRequest(tool_call_id="", tool="t", args={}, risk="write")

    def test_rejects_unknown_risk(self):
        import pytest
        from balu_code_shared.events import ApprovalRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ApprovalRequest(tool_call_id="tc_1", tool="t", args={}, risk="read")


class TestApproval:
    def test_approved_true(self):
        from balu_code_shared.events import Approval

        evt = Approval(tool_call_id="tc_1", approved=True)
        assert evt.type == "approval"
        assert evt.approved is True
        assert evt.reason is None

    def test_approved_false_with_reason(self):
        from balu_code_shared.events import Approval

        evt = Approval(
            tool_call_id="tc_1",
            approved=False,
            reason="user said no",
        )
        assert evt.approved is False
        assert evt.reason == "user said no"

    def test_rejects_empty_tool_call_id(self):
        import pytest
        from balu_code_shared.events import Approval
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Approval(tool_call_id="", approved=True)


class TestCancel:
    def test_constructs_with_turn_id(self):
        from balu_code_shared.events import Cancel

        evt = Cancel(turn_id="t_1")
        assert evt.type == "cancel"
        assert evt.turn_id == "t_1"

    def test_rejects_empty_turn_id(self):
        import pytest
        from balu_code_shared.events import Cancel
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Cancel(turn_id="")


class TestStopReasonMaxTokens:
    def test_max_tokens_is_valid(self):
        evt = TurnEnd(
            turn_id="t_1",
            total_tokens=100,
            iterations=2,
            stop_reason="max_tokens",
        )
        assert evt.stop_reason == "max_tokens"


class TestParseFrameNewEvents:
    def test_parses_approval_request(self):
        from balu_code_shared.events import ApprovalRequest, parse_frame

        evt = parse_frame(
            {
                "type": "approval_request",
                "tool_call_id": "tc_1",
                "tool": "run_bash",
                "args": {"command": "ls"},
                "risk": "exec",
            }
        )
        assert isinstance(evt, ApprovalRequest)
        assert evt.risk == "exec"

    def test_parses_approval(self):
        from balu_code_shared.events import Approval, parse_frame

        evt = parse_frame(
            {"type": "approval", "tool_call_id": "tc_1", "approved": True}
        )
        assert isinstance(evt, Approval)

    def test_parses_cancel(self):
        from balu_code_shared.events import Cancel, parse_frame

        evt = parse_frame({"type": "cancel", "turn_id": "t_1"})
        assert isinstance(evt, Cancel)
```

Replace the existing `test_event_union_includes_all_seven`:

```python
def test_event_union_includes_all_ten():
    import typing

    annotated_args = typing.get_args(Event)
    union_type = annotated_args[0]
    members = typing.get_args(union_type)
    names = {m.model_fields["type"].default for m in members}
    assert names == {
        "user_message",
        "turn_start",
        "token",
        "turn_end",
        "error",
        "tool_call",
        "tool_result",
        "approval_request",
        "approval",
        "cancel",
    }
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest shared/tests/test_events.py -v
```
Expected: failures on `TestApprovalRequest`, `TestApproval`, `TestCancel`, `TestStopReasonMaxTokens`, `TestParseFrameNewEvents`, `test_event_union_includes_all_ten` (imports fail / union mismatch).

- [ ] **Step 3: Update `shared/src/balu_code_shared/events.py`**

Replace the entire file with:

```python
"""WebSocket event envelopes shared by the Balu Code plugin and CLI.

Each envelope has a literal ``type`` discriminator. ``parse_frame`` uses
a Pydantic discriminated union to dispatch an incoming dict to the right
model, which is the single source of truth both sides rely on.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

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


StopReason = Literal["done", "max_iter", "max_tokens", "error", "cancelled"]


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


Event = Annotated[
    UserMessage
    | TurnStart
    | Token
    | TurnEnd
    | Error
    | ToolCall
    | ToolResult
    | ApprovalRequest
    | Approval
    | Cancel,
    Field(discriminator="type"),
]


_adapter: TypeAdapter[Event] = TypeAdapter(Event)


def parse_frame(data: dict[str, Any]) -> Event:
    """Deserialise a dict-shaped WebSocket frame into the matching Event model."""
    return _adapter.validate_python(data)


__all__ = [
    "Approval",
    "ApprovalRequest",
    "Cancel",
    "Error",
    "Event",
    "StopReason",
    "Token",
    "ToolCall",
    "ToolResult",
    "TurnEnd",
    "TurnStart",
    "UserMessage",
    "parse_frame",
]
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest shared/tests/test_events.py -v
```
Expected: all green.

- [ ] **Step 5: Run full shared + plugin suite — no regression**

```bash
pytest -q
```
Expected: 248 + ~14 new = ~262 passed.

- [ ] **Step 6: Commit**

```bash
git add shared/src/balu_code_shared/events.py shared/tests/test_events.py
git commit -m "feat(shared): add ApprovalRequest/Approval/Cancel envelopes + max_tokens stop reason"
```

---

## Task 3: `plugin/services/paths.py` — single source of truth for path containment

Extracts the inline `_contained` helper currently sitting in `read_file.py` and hardens it against symlink-escape + absolute-path + empty-path inputs. All file-system tools will import `resolve_within_project` from here.

**Files:**
- Create: `plugin/services/paths.py`
- Create: `plugin/tests/test_paths.py`
- Modify: `plugin/services/tools/read_file.py`
- Modify: `plugin/tests/test_tool_read_file.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_paths.py`:

```python
"""Tests for path-containment helper."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from plugin.services.paths import PathEscapesProjectError, resolve_within_project


def test_happy_path_relative_file(tmp_path: Path) -> None:
    target = tmp_path / "src" / "foo.py"
    target.parent.mkdir()
    target.write_text("x")
    resolved = resolve_within_project(tmp_path, "src/foo.py")
    assert resolved == (tmp_path / "src" / "foo.py").resolve()


def test_happy_path_file_that_does_not_exist_yet(tmp_path: Path) -> None:
    resolved = resolve_within_project(tmp_path, "new/file.py")
    assert resolved == (tmp_path / "new" / "file.py").resolve()


def test_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within_project(tmp_path, "/etc/passwd")


def test_rejects_dotdot_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within_project(tmp_path, "../outside.py")


def test_rejects_embedded_dotdot(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within_project(tmp_path, "src/../../escape.py")


def test_rejects_empty_path(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within_project(tmp_path, "")


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-target"
    outside.mkdir(exist_ok=True)
    try:
        link = tmp_path / "escape-link"
        os.symlink(outside, link)
        with pytest.raises(PathEscapesProjectError):
            resolve_within_project(tmp_path, "escape-link/secret.txt")
    finally:
        if outside.exists():
            for child in outside.iterdir():
                child.unlink()
            outside.rmdir()


def test_normalises_redundant_separators(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.txt").write_text("x")
    resolved = resolve_within_project(tmp_path, "a//b.txt")
    assert resolved == (tmp_path / "a" / "b.txt").resolve()
```

- [ ] **Step 2: Run and verify they fail**

```bash
pytest plugin/tests/test_paths.py -v
```
Expected: `ModuleNotFoundError: No module named 'plugin.services.paths'`.

- [ ] **Step 3: Implement `plugin/services/paths.py`**

```python
"""Project-root path-containment helper.

Used by every file-system-touching tool. Rejects absolute paths, ``..``
traversal (including via symlinks), and empty inputs. Works for both
existing and not-yet-existing targets — creation is a valid use case.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


class PathEscapesProjectError(ValueError):
    """The requested path would escape the project root."""


def resolve_within_project(project_root: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` relative to ``project_root`` and verify containment."""
    if not rel_path or rel_path != rel_path.strip():
        raise PathEscapesProjectError(f"path must be a non-empty trimmed string, got {rel_path!r}")

    if PurePosixPath(rel_path).is_absolute() or Path(rel_path).is_absolute():
        raise PathEscapesProjectError(f"path '{rel_path}' is absolute")

    root_resolved = project_root.resolve(strict=False)
    candidate = (root_resolved / rel_path).resolve(strict=False)

    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise PathEscapesProjectError(
            f"path '{rel_path}' escapes project root {root_resolved}"
        ) from exc

    return candidate


__all__ = ["PathEscapesProjectError", "resolve_within_project"]
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest plugin/tests/test_paths.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Migrate `read_file.py` to use the new helper**

Replace `plugin/services/tools/read_file.py` with:

```python
"""read_file tool — read a project-root-relative text file."""

from __future__ import annotations

from pydantic import BaseModel, Field

from plugin.services.paths import PathEscapesProjectError, resolve_within_project
from plugin.services.tools.base import ToolContext, ToolResult


class ReadFileArgs(BaseModel):
    path: str = Field(..., min_length=1, description="Path relative to project root.")
    max_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1,
        le=10 * 1024 * 1024,
        description="Maximum bytes to read (default 2 MB, cap 10 MB).",
    )


class ReadFileTool:
    name = "read_file"
    description = (
        "Read the contents of a text file relative to the project root. "
        "Returns up to 2 MB by default."
    )
    args_schema = ReadFileArgs
    risk = "read"

    async def execute(self, args: ReadFileArgs, ctx: ToolContext) -> ToolResult:
        try:
            resolved = resolve_within_project(ctx.project_root, args.path)
        except PathEscapesProjectError as exc:
            return ToolResult(status="error", text="", error=str(exc))

        if not resolved.exists():
            return ToolResult(
                status="error",
                text="",
                error=f"file '{args.path}' not found",
            )
        if not resolved.is_file():
            return ToolResult(
                status="error",
                text="",
                error=f"path '{args.path}' is not a regular file",
            )
        try:
            with resolved.open("rb") as f:
                raw = f.read(args.max_bytes)
        except OSError as exc:
            return ToolResult(
                status="error",
                text="",
                error=f"could not read '{args.path}': {exc}",
            )
        if b"\x00" in raw[:1024]:
            return ToolResult(
                status="error",
                text="",
                error=f"'{args.path}' appears to be a binary file",
            )
        text = raw.decode("utf-8", errors="replace")
        return ToolResult(status="ok", text=text, bytes_out=len(raw))


__all__ = ["ReadFileArgs", "ReadFileTool"]
```

- [ ] **Step 6: Update `plugin/tests/test_tool_read_file.py` error-message assertions**

Find every assertion that currently checks for a substring like `"escapes project root"` and make sure it still matches after the migration. The new error carries the resolved-root suffix. Search-and-update:

```bash
grep -n "escapes project root" plugin/tests/test_tool_read_file.py
```

For each matching assertion, update to:
```python
assert "escapes project root" in result.error
```
(Use `in` instead of `==` so the resolved-root suffix is accepted.)

- [ ] **Step 7: Run read_file + path tests**

```bash
pytest plugin/tests/test_tool_read_file.py plugin/tests/test_paths.py -v
```
Expected: all green.

- [ ] **Step 8: Run full suite — no regression**

```bash
pytest -q
```
Expected: ~270 passed.

- [ ] **Step 9: Commit**

```bash
git add plugin/services/paths.py plugin/services/tools/read_file.py \
        plugin/tests/test_paths.py plugin/tests/test_tool_read_file.py
git commit -m "refactor(plugin): extract path-containment to plugin/services/paths.py"
```

---

## Task 4: `CancelToken` service + extend `ToolContext`

A thin `asyncio.Event`-backed cancellation primitive. `ToolContext` gets a `cancel_token` field so every existing 4a tool receives one transparently (and ignores it — they're fast); only `run_bash` uses it actively in Task 7.

**Files:**
- Create: `plugin/services/cancel.py`
- Create: `plugin/tests/test_cancel.py`
- Modify: `plugin/services/tools/base.py`
- Modify: `plugin/tests/test_tool_base.py`
- Modify: `plugin/tests/test_tool_read_file.py`
- Modify: `plugin/tests/test_tool_glob.py`
- Modify: `plugin/tests/test_tool_grep.py`

- [ ] **Step 1: Write the failing tests for `CancelToken`**

Create `plugin/tests/test_cancel.py`:

```python
"""Tests for CancelToken."""
from __future__ import annotations

import asyncio

import pytest

from plugin.services.cancel import CancelToken


def test_starts_not_cancelled() -> None:
    tok = CancelToken()
    assert tok.cancelled is False


def test_cancel_sets_flag() -> None:
    tok = CancelToken()
    tok.cancel()
    assert tok.cancelled is True


def test_check_raises_when_cancelled() -> None:
    tok = CancelToken()
    tok.cancel()
    with pytest.raises(asyncio.CancelledError):
        tok.check()


def test_check_is_noop_when_not_cancelled() -> None:
    tok = CancelToken()
    tok.check()


@pytest.mark.asyncio
async def test_wait_blocks_until_cancelled() -> None:
    tok = CancelToken()

    async def canceller() -> None:
        await asyncio.sleep(0.01)
        tok.cancel()

    async with asyncio.TaskGroup() as tg:
        tg.create_task(canceller())
        await asyncio.wait_for(tok.wait(), timeout=1.0)

    assert tok.cancelled is True


@pytest.mark.asyncio
async def test_wait_returns_immediately_if_already_cancelled() -> None:
    tok = CancelToken()
    tok.cancel()
    await asyncio.wait_for(tok.wait(), timeout=0.1)
```

- [ ] **Step 2: Run and verify they fail**

```bash
pytest plugin/tests/test_cancel.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `plugin/services/cancel.py`**

```python
"""Cooperative cancellation primitive.

A single ``CancelToken`` is created per turn by the WS handler and
passed into ``run_turn`` + every ``Tool.execute`` via ``ToolContext``.
The loop sprinkles ``cancel_token.check()`` between Ollama stream
chunks and before each tool dispatch (soft cancel); long-running tools
like ``run_bash`` ``await cancel_token.wait()`` from a watcher task to
kill subprocesses (hard cancel).
"""

from __future__ import annotations

import asyncio


class CancelToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        """Raise CancelledError if the token has been flipped."""
        if self._event.is_set():
            raise asyncio.CancelledError("cancelled by user")

    async def wait(self) -> None:
        """Await until the token is flipped."""
        await self._event.wait()


__all__ = ["CancelToken"]
```

- [ ] **Step 4: Run cancel tests — verify they pass**

```bash
pytest plugin/tests/test_cancel.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Extend `ToolContext` with `cancel_token`**

Replace `plugin/services/tools/base.py` with:

```python
"""Tool Protocol + lightweight value types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from plugin.services.cancel import CancelToken


@dataclass(frozen=True)
class ToolContext:
    project_root: Path
    project_id: int
    turn_id: str
    cancel_token: CancelToken


@dataclass(frozen=True)
class ToolResult:
    status: Literal["ok", "error"]
    text: str
    bytes_out: int = 0
    error: str | None = None


class Tool(Protocol):
    name: str
    description: str
    args_schema: type[BaseModel]
    risk: Literal["read", "write", "exec", "network"]

    async def execute(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...


__all__ = ["Tool", "ToolContext", "ToolResult"]
```

- [ ] **Step 6: Update `test_tool_base.py`**

Find any `ToolContext(...)` construction in `plugin/tests/test_tool_base.py` and add `cancel_token=CancelToken()`:

```python
from plugin.services.cancel import CancelToken
from plugin.services.tools.base import ToolContext

ctx = ToolContext(
    project_root=tmp_path,
    project_id=1,
    turn_id="t_test",
    cancel_token=CancelToken(),
)
```

- [ ] **Step 7: Update `test_tool_read_file.py`, `test_tool_glob.py`, `test_tool_grep.py`**

In each file, add `cancel_token=CancelToken()` to every `ToolContext(...)` construction. Scoping:

```bash
grep -n "ToolContext(" plugin/tests/test_tool_read_file.py plugin/tests/test_tool_glob.py plugin/tests/test_tool_grep.py
```

For each hit, add the new field as shown in Step 6.

If any test file uses a pytest fixture for `ToolContext`, add `cancel_token=CancelToken()` in the fixture once.

- [ ] **Step 8: Run tool tests — verify they pass**

```bash
pytest plugin/tests/test_tool_base.py plugin/tests/test_tool_read_file.py \
       plugin/tests/test_tool_glob.py plugin/tests/test_tool_grep.py -v
```
Expected: all green.

- [ ] **Step 9: Run full suite — `test_agent_loop.py` may also construct `ToolContext`**

```bash
pytest -q
```
Apply the same `cancel_token=CancelToken()` edit to any remaining failure site.

- [ ] **Step 10: Commit**

```bash
git add plugin/services/cancel.py plugin/services/tools/base.py plugin/tests/test_cancel.py \
        plugin/tests/test_tool_base.py plugin/tests/test_tool_read_file.py \
        plugin/tests/test_tool_glob.py plugin/tests/test_tool_grep.py \
        plugin/tests/test_agent_loop.py
git commit -m "feat(plugin): add CancelToken + extend ToolContext with cancel_token"
```

---

## Task 5: `write_file` tool

Overwrite-allowed file writer. Max 2 MB, UTF-8, path-contained.

**Files:**
- Create: `plugin/services/tools/write_file.py`
- Create: `plugin/tests/test_tool_write_file.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_tool_write_file.py`:

```python
"""Tests for write_file tool."""
from __future__ import annotations

from pathlib import Path

import pytest

from plugin.services.cancel import CancelToken
from plugin.services.tools.base import ToolContext
from plugin.services.tools.write_file import WriteFileArgs, WriteFileTool


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        project_root=tmp_path,
        project_id=1,
        turn_id="t_test",
        cancel_token=CancelToken(),
    )


@pytest.mark.asyncio
async def test_creates_new_file(ctx: ToolContext) -> None:
    tool = WriteFileTool()
    result = await tool.execute(
        WriteFileArgs(path="foo.py", content="print('hi')\n"),
        ctx,
    )
    assert result.status == "ok"
    assert (ctx.project_root / "foo.py").read_text() == "print('hi')\n"
    assert "wrote" in result.text.lower()
    assert result.bytes_out == len("print('hi')\n".encode())


@pytest.mark.asyncio
async def test_overwrites_existing_file(ctx: ToolContext) -> None:
    (ctx.project_root / "foo.py").write_text("old\n")
    tool = WriteFileTool()
    result = await tool.execute(
        WriteFileArgs(path="foo.py", content="new\n"),
        ctx,
    )
    assert result.status == "ok"
    assert (ctx.project_root / "foo.py").read_text() == "new\n"


@pytest.mark.asyncio
async def test_rejects_missing_parent_without_create_dirs(ctx: ToolContext) -> None:
    tool = WriteFileTool()
    result = await tool.execute(
        WriteFileArgs(path="new/sub/foo.py", content="x"),
        ctx,
    )
    assert result.status == "error"
    assert "parent" in result.error.lower() or "directory" in result.error.lower()


@pytest.mark.asyncio
async def test_create_dirs_true_builds_missing_parents(ctx: ToolContext) -> None:
    tool = WriteFileTool()
    result = await tool.execute(
        WriteFileArgs(path="new/sub/foo.py", content="x", create_dirs=True),
        ctx,
    )
    assert result.status == "ok"
    assert (ctx.project_root / "new" / "sub" / "foo.py").read_text() == "x"


@pytest.mark.asyncio
async def test_rejects_path_traversal(ctx: ToolContext) -> None:
    tool = WriteFileTool()
    result = await tool.execute(
        WriteFileArgs(path="../escape.py", content="x"),
        ctx,
    )
    assert result.status == "error"
    assert "escape" in result.error.lower()


def test_rejects_content_over_size_cap() -> None:
    big = "x" * (2 * 1024 * 1024 + 1)  # 2 MB + 1 byte
    with pytest.raises(Exception):
        WriteFileArgs(path="big.txt", content=big)


@pytest.mark.asyncio
async def test_accepts_utf8_content(ctx: ToolContext) -> None:
    tool = WriteFileTool()
    result = await tool.execute(
        WriteFileArgs(path="umlaute.txt", content="Grüße, 你好"),
        ctx,
    )
    assert result.status == "ok"
    assert (ctx.project_root / "umlaute.txt").read_text(encoding="utf-8") == "Grüße, 你好"


@pytest.mark.asyncio
async def test_preserves_exact_bytes_no_line_ending_magic(ctx: ToolContext) -> None:
    tool = WriteFileTool()
    content = "line1\r\nline2\nline3\r"
    result = await tool.execute(
        WriteFileArgs(path="crlf.txt", content=content),
        ctx,
    )
    assert result.status == "ok"
    assert (ctx.project_root / "crlf.txt").read_bytes() == content.encode("utf-8")


def test_risk_is_write() -> None:
    assert WriteFileTool.risk == "write"
```

- [ ] **Step 2: Run and verify they fail**

```bash
pytest plugin/tests/test_tool_write_file.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `plugin/services/tools/write_file.py`**

```python
"""write_file tool — create or overwrite a project-relative text file."""

from __future__ import annotations

from pydantic import BaseModel, Field

from plugin.services.paths import PathEscapesProjectError, resolve_within_project
from plugin.services.tools.base import ToolContext, ToolResult

_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


class WriteFileArgs(BaseModel):
    path: str = Field(..., min_length=1, description="Path relative to project root.")
    content: str = Field(..., max_length=_MAX_BYTES, description="File contents (UTF-8).")
    create_dirs: bool = Field(
        default=False,
        description="If true, create missing parent directories.",
    )


class WriteFileTool:
    name = "write_file"
    description = (
        "Create or overwrite a text file relative to the project root. "
        "Content must be UTF-8, max 2 MB. Set create_dirs=true to create "
        "missing parent directories."
    )
    args_schema = WriteFileArgs
    risk = "write"

    async def execute(self, args: WriteFileArgs, ctx: ToolContext) -> ToolResult:
        try:
            resolved = resolve_within_project(ctx.project_root, args.path)
        except PathEscapesProjectError as exc:
            return ToolResult(status="error", text="", error=str(exc))

        parent = resolved.parent
        if not parent.exists():
            if not args.create_dirs:
                return ToolResult(
                    status="error",
                    text="",
                    error=f"parent directory for '{args.path}' does not exist (set create_dirs=true)",
                )
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return ToolResult(
                    status="error",
                    text="",
                    error=f"could not create parent dirs for '{args.path}': {exc}",
                )

        existed = resolved.exists()
        encoded = args.content.encode("utf-8")
        try:
            with resolved.open("wb") as f:
                f.write(encoded)
        except OSError as exc:
            return ToolResult(
                status="error",
                text="",
                error=f"could not write '{args.path}': {exc}",
            )

        verb = "overwrote" if existed else "wrote"
        summary = f"{verb} '{args.path}' ({len(encoded)} bytes)"
        return ToolResult(status="ok", text=summary, bytes_out=len(encoded))


__all__ = ["WriteFileArgs", "WriteFileTool"]
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest plugin/tests/test_tool_write_file.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add plugin/services/tools/write_file.py plugin/tests/test_tool_write_file.py
git commit -m "feat(plugin): add write_file tool (risk=write, 2 MB cap, path-contained)"
```

---

## Task 6: `apply_patch` tool

Unified-diff applier via `unidiff`. Multi-file, fail-fast, `/dev/null` for create + delete. Each target goes through `resolve_within_project`. Pass 1 validates every hunk against current file content; Pass 2 writes only after all validation succeeds (no partial applies).

**Files:**
- Create: `plugin/services/tools/apply_patch.py`
- Create: `plugin/tests/test_tool_apply_patch.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_tool_apply_patch.py`:

```python
"""Tests for apply_patch tool."""
from __future__ import annotations

from pathlib import Path

import pytest

from plugin.services.cancel import CancelToken
from plugin.services.tools.apply_patch import ApplyPatchArgs, ApplyPatchTool
from plugin.services.tools.base import ToolContext


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        project_root=tmp_path,
        project_id=1,
        turn_id="t_test",
        cancel_token=CancelToken(),
    )


@pytest.mark.asyncio
async def test_single_hunk_modification(ctx: ToolContext) -> None:
    target = ctx.project_root / "foo.txt"
    target.write_text("line1\nline2\nline3\n")
    diff = """--- a/foo.txt
+++ b/foo.txt
@@ -1,3 +1,3 @@
 line1
-line2
+LINE TWO
 line3
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "ok"
    assert target.read_text() == "line1\nLINE TWO\nline3\n"
    assert "hunk" in result.text.lower()


@pytest.mark.asyncio
async def test_multi_file_patch(ctx: ToolContext) -> None:
    a = ctx.project_root / "a.txt"
    b = ctx.project_root / "b.txt"
    a.write_text("A1\n")
    b.write_text("B1\n")
    diff = """--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-A1
+A2
--- a/b.txt
+++ b/b.txt
@@ -1 +1 @@
-B1
+B2
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "ok"
    assert a.read_text() == "A2\n"
    assert b.read_text() == "B2\n"


@pytest.mark.asyncio
async def test_creates_file_from_dev_null(ctx: ToolContext) -> None:
    diff = """--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+hello
+world
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "ok"
    assert (ctx.project_root / "new.txt").read_text() == "hello\nworld\n"


@pytest.mark.asyncio
async def test_deletes_file_to_dev_null(ctx: ToolContext) -> None:
    target = ctx.project_root / "gone.txt"
    target.write_text("bye\n")
    diff = """--- a/gone.txt
+++ /dev/null
@@ -1 +0,0 @@
-bye
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "ok"
    assert not target.exists()


@pytest.mark.asyncio
async def test_fails_fast_on_context_mismatch(ctx: ToolContext) -> None:
    target = ctx.project_root / "foo.txt"
    target.write_text("NOT the expected content\n")
    diff = """--- a/foo.txt
+++ b/foo.txt
@@ -1 +1 @@
-line1
+LINE ONE
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "error"
    assert target.read_text() == "NOT the expected content\n"


@pytest.mark.asyncio
async def test_multi_file_mismatch_leaves_all_untouched(ctx: ToolContext) -> None:
    a = ctx.project_root / "a.txt"
    b = ctx.project_root / "b.txt"
    a.write_text("A1\n")
    b.write_text("WRONG\n")
    diff = """--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-A1
+A2
--- a/b.txt
+++ b/b.txt
@@ -1 +1 @@
-B1
+B2
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "error"
    assert a.read_text() == "A1\n"
    assert b.read_text() == "WRONG\n"


@pytest.mark.asyncio
async def test_rejects_path_traversal(ctx: ToolContext) -> None:
    diff = """--- a/../escape.txt
+++ b/../escape.txt
@@ -0,0 +1 @@
+x
"""
    tool = ApplyPatchTool()
    result = await tool.execute(ApplyPatchArgs(diff=diff), ctx)
    assert result.status == "error"
    assert "escape" in result.error.lower()


@pytest.mark.asyncio
async def test_rejects_empty_diff() -> None:
    with pytest.raises(Exception):
        ApplyPatchArgs(diff="")


def test_risk_is_write() -> None:
    assert ApplyPatchTool.risk == "write"
```

- [ ] **Step 2: Run and verify they fail**

```bash
pytest plugin/tests/test_tool_apply_patch.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `plugin/services/tools/apply_patch.py`**

```python
"""apply_patch tool — apply a unified diff via unidiff.

Multi-file diffs are validated up-front against current file content;
if any hunk doesn't match, nothing is written (no partial applies).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from unidiff import PatchSet

from plugin.services.paths import PathEscapesProjectError, resolve_within_project
from plugin.services.tools.base import ToolContext, ToolResult

_DEV_NULL = "/dev/null"


class ApplyPatchArgs(BaseModel):
    diff: str = Field(..., min_length=1, description="Unified-diff text.")


class ApplyPatchTool:
    name = "apply_patch"
    description = (
        "Apply a unified-diff patch to one or more files (multi-file patches "
        "supported). Use --- /dev/null to create, +++ /dev/null to delete. "
        "Fails atomically — if any hunk mismatches, no file is modified."
    )
    args_schema = ApplyPatchArgs
    risk = "write"

    async def execute(self, args: ApplyPatchArgs, ctx: ToolContext) -> ToolResult:
        try:
            patch_set = PatchSet.from_string(args.diff)
        except Exception as exc:
            return ToolResult(
                status="error",
                text="",
                error=f"could not parse diff: {exc}",
            )

        if len(patch_set) == 0:
            return ToolResult(
                status="error",
                text="",
                error="diff contains no files",
            )

        planned: list[tuple[Path, str, bytes | None]] = []
        hunks_total = 0

        for patched_file in patch_set:
            source = patched_file.source_file or ""
            target = patched_file.target_file or ""

            is_create = source == _DEV_NULL or source.endswith(_DEV_NULL)
            is_delete = target == _DEV_NULL or target.endswith(_DEV_NULL)

            rel_source = _strip_prefix(source) if not is_create else None
            rel_target = _strip_prefix(target) if not is_delete else None
            rel = rel_target or rel_source
            if rel is None:
                return ToolResult(
                    status="error",
                    text="",
                    error="diff has neither source nor target path",
                )

            try:
                resolved = resolve_within_project(ctx.project_root, rel)
            except PathEscapesProjectError as e2:
                return ToolResult(status="error", text="", error=str(e2))

            if is_delete:
                if not resolved.exists():
                    return ToolResult(
                        status="error",
                        text="",
                        error=f"cannot delete '{rel}': file does not exist",
                    )
                planned.append((resolved, "delete", None))
                hunks_total += len(patched_file)
                continue

            if is_create:
                if resolved.exists():
                    return ToolResult(
                        status="error",
                        text="",
                        error=f"cannot create '{rel}': file already exists",
                    )
                pieces: list[str] = []
                for hunk in patched_file:
                    for line in hunk:
                        if line.is_added:
                            pieces.append(line.value)
                planned.append((resolved, "create", "".join(pieces).encode("utf-8")))
                hunks_total += len(patched_file)
                continue

            try:
                current = resolved.read_text(encoding="utf-8")
            except OSError as exc:
                return ToolResult(
                    status="error",
                    text="",
                    error=f"could not read '{rel}' for patching: {exc}",
                )
            try:
                new_text = _apply_hunks_to_text(current, patched_file)
            except _HunkMismatch as exc:
                return ToolResult(
                    status="error",
                    text="",
                    error=f"patch to '{rel}' did not apply cleanly: {exc}",
                )
            planned.append((resolved, "modify", new_text.encode("utf-8")))
            hunks_total += len(patched_file)

        changed: list[str] = []
        for resolved, action, new_bytes in planned:
            try:
                rel_display = str(resolved.relative_to(ctx.project_root.resolve()))
            except ValueError:
                rel_display = str(resolved)

            if action == "delete":
                try:
                    resolved.unlink()
                except OSError as exc:
                    return ToolResult(
                        status="error",
                        text="",
                        error=f"could not delete '{rel_display}': {exc}",
                    )
                changed.append(f"-{rel_display}")
                continue

            try:
                resolved.parent.mkdir(parents=True, exist_ok=True)
                with resolved.open("wb") as f:
                    f.write(new_bytes or b"")
            except OSError as exc:
                return ToolResult(
                    status="error",
                    text="",
                    error=f"could not write '{rel_display}': {exc}",
                )
            changed.append(f"{'+' if action == 'create' else '~'}{rel_display}")

        bytes_out = sum(len(b or b"") for _, _, b in planned)
        summary = (
            f"applied {hunks_total} hunk(s) across {len(changed)} file(s): "
            + ", ".join(changed)
        )
        return ToolResult(status="ok", text=summary, bytes_out=bytes_out)


def _strip_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


class _HunkMismatch(Exception):
    """Raised when a hunk's context doesn't match the current file."""


def _apply_hunks_to_text(current: str, patched_file) -> str:
    lines = current.splitlines(keepends=True)
    result: list[str] = []
    cursor = 0

    for hunk in patched_file:
        src_start = max(hunk.source_start - 1, 0)
        if src_start < cursor:
            raise _HunkMismatch("hunk starts before cursor (overlap or out-of-order hunks)")
        result.extend(lines[cursor:src_start])
        cursor = src_start

        for line in hunk:
            if line.is_context or line.is_removed:
                if cursor >= len(lines):
                    raise _HunkMismatch(
                        f"expected line {cursor + 1} but file has only {len(lines)} lines"
                    )
                actual = lines[cursor]
                expected = line.value
                if actual.rstrip("\r\n") != expected.rstrip("\r\n"):
                    raise _HunkMismatch(
                        f"at line {cursor + 1}: expected {expected.rstrip()!r}, got {actual.rstrip()!r}"
                    )
                if line.is_context:
                    result.append(actual)
                cursor += 1
            elif line.is_added:
                result.append(line.value)

    result.extend(lines[cursor:])
    return "".join(result)


__all__ = ["ApplyPatchArgs", "ApplyPatchTool"]
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest plugin/tests/test_tool_apply_patch.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add plugin/services/tools/apply_patch.py plugin/tests/test_tool_apply_patch.py
git commit -m "feat(plugin): add apply_patch tool (unidiff, fail-fast, multi-file)"
```

---

## Task 7: `run_bash` tool

Shell command runner with timeout + output tail-truncation. Watches the cancel token so a mid-turn cancel kills the subprocess (SIGTERM, 2 s grace, SIGKILL). The subprocess is spawned in its own process group so the kill reaches children too.

**Files:**
- Create: `plugin/services/tools/run_bash.py`
- Create: `plugin/tests/test_tool_run_bash.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_tool_run_bash.py`:

```python
"""Tests for run_bash tool."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from plugin.services.cancel import CancelToken
from plugin.services.tools.base import ToolContext
from plugin.services.tools.run_bash import RunBashArgs, RunBashTool


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        project_root=tmp_path,
        project_id=1,
        turn_id="t_test",
        cancel_token=CancelToken(),
    )


@pytest.mark.asyncio
async def test_exit_zero_returns_ok(ctx: ToolContext) -> None:
    tool = RunBashTool()
    result = await tool.execute(RunBashArgs(command="echo hello"), ctx)
    assert result.status == "ok"
    assert "hello" in result.text
    assert "exit_code: 0" in result.text


@pytest.mark.asyncio
async def test_exit_nonzero_returns_error(ctx: ToolContext) -> None:
    tool = RunBashTool()
    result = await tool.execute(RunBashArgs(command="exit 3"), ctx)
    assert result.status == "error"
    assert "3" in result.text


@pytest.mark.asyncio
async def test_stdout_and_stderr_merged(ctx: ToolContext) -> None:
    tool = RunBashTool()
    result = await tool.execute(
        RunBashArgs(command="echo out; echo err >&2"),
        ctx,
    )
    assert result.status == "ok"
    assert "out" in result.text
    assert "err" in result.text


@pytest.mark.asyncio
async def test_cwd_is_project_root(ctx: ToolContext) -> None:
    (ctx.project_root / "marker").write_text("x")
    tool = RunBashTool()
    result = await tool.execute(RunBashArgs(command="ls"), ctx)
    assert result.status == "ok"
    assert "marker" in result.text


@pytest.mark.asyncio
async def test_timeout_clamped_and_enforced(ctx: ToolContext) -> None:
    tool = RunBashTool()
    result = await tool.execute(
        RunBashArgs(command="sleep 5", timeout_s=1),
        ctx,
    )
    assert result.status == "error"
    assert "timeout" in result.text.lower() or "timeout" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_cancel_token_kills_subprocess(ctx: ToolContext) -> None:
    tool = RunBashTool()

    async def canceller() -> None:
        await asyncio.sleep(0.3)
        ctx.cancel_token.cancel()

    task = asyncio.create_task(canceller())
    result = await tool.execute(
        RunBashArgs(command="sleep 10", timeout_s=30),
        ctx,
    )
    await task
    assert result.status == "error"
    assert "cancel" in (result.error or "").lower() or "cancel" in result.text.lower()


@pytest.mark.asyncio
async def test_output_tail_truncation(ctx: ToolContext) -> None:
    tool = RunBashTool()
    result = await tool.execute(
        RunBashArgs(command="yes x | head -c 524288"),
        ctx,
    )
    assert result.status == "ok"
    assert len(result.text.encode("utf-8")) <= 300_000


@pytest.mark.asyncio
async def test_env_path_is_pinned(ctx: ToolContext) -> None:
    tool = RunBashTool()
    result = await tool.execute(RunBashArgs(command="echo $PATH"), ctx)
    assert result.status == "ok"
    assert "/usr/bin" in result.text


@pytest.mark.asyncio
async def test_env_strips_baluhost_keys(ctx: ToolContext, monkeypatch) -> None:
    monkeypatch.setenv("BALUHOST_SECRET", "should-not-leak")
    tool = RunBashTool()
    result = await tool.execute(
        RunBashArgs(command="env | grep -c BALUHOST || true"),
        ctx,
    )
    assert result.status == "ok"
    last = [ln for ln in result.text.splitlines() if ln.strip()][-1]
    assert last.strip() == "0"


def test_risk_is_exec() -> None:
    assert RunBashTool.risk == "exec"
```

- [ ] **Step 2: Run and verify they fail**

```bash
pytest plugin/tests/test_tool_run_bash.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `plugin/services/tools/run_bash.py`**

Note: the tool spawns bash via `asyncio.create_subprocess_exec("/bin/bash", "-c", command)` — the command string is passed as an argv to bash, not interpolated into a shell template from the caller, so there is no shell-injection surface on the Python side. The command runs inside bash (which is the whole point of the tool — the agent is allowed to run arbitrary shell commands). The approval gate upstream is what governs whether a given command is allowed to run.

```python
"""run_bash tool — run a shell command with timeout + hard cancel."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from pydantic import BaseModel, Field

from plugin.services.tools.base import ToolContext, ToolResult

_TAIL_BYTES = 256 * 1024
_GRACE_S = 2.0


class RunBashArgs(BaseModel):
    command: str = Field(..., min_length=1, description="Shell command (bash -c).")
    timeout_s: int = Field(default=60, ge=1, le=300, description="Timeout in seconds.")


class RunBashTool:
    name = "run_bash"
    description = (
        "Run a shell command (bash -c) in the project root. Combined "
        "stdout+stderr is returned (truncated head+tail for long output). "
        "Default timeout 60 s (max 300 s)."
    )
    args_schema = RunBashArgs
    risk = "exec"

    async def execute(self, args: RunBashArgs, ctx: ToolContext) -> ToolResult:
        env = _sanitised_env()
        try:
            proc = await asyncio.create_subprocess_exec(
                "/bin/bash",
                "-c",
                args.command,
                cwd=str(ctx.project_root),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as e1:
            return ToolResult(
                status="error",
                text="",
                error=f"could not spawn subprocess: {e1}",
            )

        cancel_watcher = asyncio.create_task(_watch_cancel(ctx.cancel_token, proc))
        timed_out = False

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=args.timeout_s)
        except asyncio.TimeoutError:
            timed_out = True
            _kill_process_group(proc)
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_GRACE_S)
            except asyncio.TimeoutError:
                proc.kill()
                stdout, _ = await proc.communicate()
        finally:
            cancel_watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_watcher

        cancelled = ctx.cancel_token.cancelled
        raw = stdout or b""
        output = _tail_truncate(raw.decode("utf-8", errors="replace"), _TAIL_BYTES)
        exit_code = proc.returncode if proc.returncode is not None else -1

        if cancelled:
            return ToolResult(
                status="error",
                text=f"exit_code: {exit_code}\ncancelled by user\n---\n{output}",
                bytes_out=len(raw),
                error="cancelled by user",
            )
        if timed_out:
            return ToolResult(
                status="error",
                text=f"exit_code: {exit_code}\ntimeout after {args.timeout_s}s\n---\n{output}",
                bytes_out=len(raw),
                error=f"timeout after {args.timeout_s}s",
            )
        header = f"exit_code: {exit_code}\n---\n"
        if exit_code == 0:
            return ToolResult(status="ok", text=header + output, bytes_out=len(raw))
        return ToolResult(
            status="error",
            text=header + output,
            bytes_out=len(raw),
            error=f"command failed with exit code {exit_code}",
        )


def _sanitised_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("BALUHOST_")}
    env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    return env


async def _watch_cancel(token, proc) -> None:
    try:
        await token.wait()
    except asyncio.CancelledError:
        return
    if proc.returncode is None:
        _kill_process_group(proc)


def _kill_process_group(proc) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _tail_truncate(s: str, budget: int) -> str:
    encoded = s.encode("utf-8")
    if len(encoded) <= 2 * budget:
        return s
    head = encoded[:budget].decode("utf-8", errors="replace")
    tail = encoded[-budget:].decode("utf-8", errors="replace")
    dropped = len(encoded) - 2 * budget
    return f"{head}\n\n... [{dropped} bytes truncated] ...\n\n{tail}"


__all__ = ["RunBashArgs", "RunBashTool"]
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest plugin/tests/test_tool_run_bash.py -v
```
Expected: 10 passed. Cancel and timeout tests take ~1-2 s each.

- [ ] **Step 5: Commit**

```bash
git add plugin/services/tools/run_bash.py plugin/tests/test_tool_run_bash.py
git commit -m "feat(plugin): add run_bash tool (timeout, sanitised env, hard cancel)"
```

---

## Task 8: `web_fetch` tool

HTTP fetcher with SSRF guard + Readability extraction. HTML goes through `trafilatura`; other content types returned raw up to `max_bytes`. The SSRF guard runs at request-time *and* on every redirect via an httpx event hook.

**Files:**
- Create: `plugin/services/tools/web_fetch.py`
- Create: `plugin/tests/test_tool_web_fetch.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_tool_web_fetch.py`:

```python
"""Tests for web_fetch tool — offline fixtures via httpx.MockTransport."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from plugin.services.cancel import CancelToken
from plugin.services.tools.base import ToolContext
from plugin.services.tools.web_fetch import WebFetchArgs, WebFetchTool


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        project_root=tmp_path,
        project_id=1,
        turn_id="t_test",
        cancel_token=CancelToken(),
    )


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_html_extraction_via_trafilatura(ctx: ToolContext) -> None:
    def handler(request):
        return httpx.Response(
            200,
            text="<html><body><h1>Hello</h1><p>World-content-1234</p></body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )

    tool = WebFetchTool(transport=_transport(handler))
    result = await tool.execute(WebFetchArgs(url="https://example.com/"), ctx)
    assert result.status == "ok"
    assert "World-content-1234" in result.text


@pytest.mark.asyncio
async def test_non_html_returned_raw(ctx: ToolContext) -> None:
    def handler(request):
        return httpx.Response(
            200,
            text='{"hello": "world"}',
            headers={"content-type": "application/json"},
        )

    tool = WebFetchTool(transport=_transport(handler))
    result = await tool.execute(WebFetchArgs(url="https://example.com/api"), ctx)
    assert result.status == "ok"
    assert '"hello": "world"' in result.text


@pytest.mark.asyncio
async def test_max_bytes_truncates(ctx: ToolContext) -> None:
    big_text = "x" * 2000
    def handler(request):
        return httpx.Response(200, text=big_text, headers={"content-type": "text/plain"})

    tool = WebFetchTool(transport=_transport(handler))
    result = await tool.execute(
        WebFetchArgs(url="https://example.com/big", max_bytes=1024),
        ctx,
    )
    assert result.status == "ok"
    assert len(result.text.encode("utf-8")) <= 1024


@pytest.mark.asyncio
async def test_rejects_localhost_by_hostname(ctx: ToolContext) -> None:
    tool = WebFetchTool()
    result = await tool.execute(WebFetchArgs(url="http://localhost:8000/"), ctx)
    assert result.status == "error"
    assert "localhost" in result.error.lower() or "private" in result.error.lower()


@pytest.mark.asyncio
async def test_rejects_private_ip(ctx: ToolContext) -> None:
    tool = WebFetchTool()
    result = await tool.execute(WebFetchArgs(url="http://10.0.0.1/"), ctx)
    assert result.status == "error"


@pytest.mark.asyncio
async def test_rejects_link_local(ctx: ToolContext) -> None:
    tool = WebFetchTool()
    result = await tool.execute(WebFetchArgs(url="http://169.254.169.254/"), ctx)
    assert result.status == "error"


@pytest.mark.asyncio
async def test_rejects_ipv6_loopback(ctx: ToolContext) -> None:
    tool = WebFetchTool()
    result = await tool.execute(WebFetchArgs(url="http://[::1]/"), ctx)
    assert result.status == "error"


def test_risk_is_network() -> None:
    assert WebFetchTool.risk == "network"
```

- [ ] **Step 2: Run and verify they fail**

```bash
pytest plugin/tests/test_tool_web_fetch.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `plugin/services/tools/web_fetch.py`**

```python
"""web_fetch tool — HTTP fetch with SSRF guard + Readability extraction."""

from __future__ import annotations

import ipaddress
import socket
from typing import Optional

import httpx
import trafilatura
from pydantic import BaseModel, Field, HttpUrl

from plugin.services.tools.base import ToolContext, ToolResult

_TIMEOUT_S = 20.0
_MAX_REDIRECTS = 5


class WebFetchArgs(BaseModel):
    url: HttpUrl = Field(..., description="Absolute http(s) URL.")
    max_bytes: int = Field(
        default=500_000,
        ge=1024,
        le=2 * 1024 * 1024,
        description="Maximum bytes of response content to return.",
    )


class WebFetchTool:
    name = "web_fetch"
    description = (
        "Fetch a URL (http/https). Returns readable text extracted from HTML "
        "pages; other content types are returned raw (truncated). Private/"
        "loopback/link-local IPs are blocked."
    )
    args_schema = WebFetchArgs
    risk = "network"

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._transport = transport

    async def execute(self, args: WebFetchArgs, ctx: ToolContext) -> ToolResult:
        url = str(args.url)
        try:
            _guard_host(url)
        except _SSRFBlocked as e1:
            return ToolResult(status="error", text="", error=f"ssrf: {e1}")

        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=_TIMEOUT_S,
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            event_hooks={"response": [_check_redirect_host]},
        ) as client:
            try:
                response = await client.get(url)
            except _SSRFBlocked as e2:
                return ToolResult(status="error", text="", error=f"ssrf after redirect: {e2}")
            except httpx.TooManyRedirects as e3:
                return ToolResult(status="error", text="", error=f"too many redirects: {e3}")
            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as e4:
                return ToolResult(status="error", text="", error=f"fetch failed: {e4}")

        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        raw_bytes = response.content[: args.max_bytes]

        if content_type in ("text/html", "application/xhtml+xml"):
            html = raw_bytes.decode(response.encoding or "utf-8", errors="replace")
            extracted = trafilatura.extract(html) or ""
            text = extracted.strip() or html[: args.max_bytes]
        else:
            text = raw_bytes.decode(response.encoding or "utf-8", errors="replace")

        summary = f"GET {response.url} -> {response.status_code} ({content_type})\n---\n{text}"
        summary_bytes = summary.encode("utf-8")[: args.max_bytes]
        return ToolResult(
            status="ok" if response.is_success else "error",
            text=summary_bytes.decode("utf-8", errors="replace"),
            bytes_out=len(raw_bytes),
            error=None if response.is_success else f"http status {response.status_code}",
        )


class _SSRFBlocked(Exception):
    pass


def _guard_host(url: str) -> None:
    parsed = httpx.URL(url)
    host = parsed.host
    if not host:
        raise _SSRFBlocked(f"no host in url {url}")
    if host.lower() == "localhost":
        raise _SSRFBlocked("localhost is blocked")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e1:
        raise _SSRFBlocked(f"dns failed for {host}: {e1}") from e1
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
            raise _SSRFBlocked(f"{host} resolves to {ip_str} which is not reachable")


async def _check_redirect_host(response) -> None:
    if response.is_redirect:
        location = response.headers.get("location")
        if location:
            target = str(httpx.URL(response.url).join(location))
            _guard_host(target)


__all__ = ["WebFetchArgs", "WebFetchTool"]
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest plugin/tests/test_tool_web_fetch.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add plugin/services/tools/web_fetch.py plugin/tests/test_tool_web_fetch.py
git commit -m "feat(plugin): add web_fetch tool (SSRF guard + trafilatura extraction)"
```

---

## Task 9: `AuditLogger` wrapper + `TurnDeps` + deps.py wiring

Thin async wrapper around BaluHost's sync `AuditLoggerDB.log_event`. Maps tool-call metadata to the DB-logger's shape (`event_type="BALU_CODE"`, `action=f"tool:{name}"`, rest in `details`). Registered as a new singleton.

**Files:**
- Create: `plugin/services/audit.py`
- Create: `plugin/tests/test_audit.py`
- Modify: `plugin/deps.py`
- Modify: `plugin/__init__.py`
- Modify: `plugin/services/agent_loop.py` (only the `TurnDeps` field)
- Modify: `plugin/tests/test_plugin_lifecycle.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_audit.py`:

```python
"""Tests for AuditLogger wrapper."""
from __future__ import annotations

from typing import Any

import pytest

from plugin.services.audit import AuditLogger


class _FakeDBLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def log_event(
        self,
        *,
        event_type,
        user,
        action,
        resource=None,
        details=None,
        success=True,
        error_message=None,
        ip_address=None,
        user_agent=None,
        db=None,
    ):
        self.calls.append(
            {
                "event_type": event_type,
                "user": user,
                "action": action,
                "resource": resource,
                "details": details,
                "success": success,
                "error_message": error_message,
            }
        )
        return object()


@pytest.mark.asyncio
async def test_records_ok_tool_call_as_balu_code_event() -> None:
    fake = _FakeDBLogger()
    logger = AuditLogger(fake)
    await logger.record_tool_call(
        tool="write_file",
        user="sven",
        turn_id="t_1",
        tool_call_id="tc_1",
        args={"path": "foo.py", "content": "x"},
        status="ok",
        bytes_out=1,
        error=None,
        approved=True,
        auto_approved=False,
    )
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["event_type"] == "BALU_CODE"
    assert call["user"] == "sven"
    assert call["action"] == "tool:write_file"
    assert call["resource"] == "foo.py"
    assert call["success"] is True
    assert call["details"]["turn_id"] == "t_1"
    assert call["details"]["approved"] is True
    assert call["details"]["auto_approved"] is False


@pytest.mark.asyncio
async def test_records_error_and_rejection() -> None:
    fake = _FakeDBLogger()
    logger = AuditLogger(fake)
    await logger.record_tool_call(
        tool="run_bash",
        user="sven",
        turn_id="t_1",
        tool_call_id="tc_2",
        args={"command": "rm -rf /"},
        status="error",
        bytes_out=0,
        error="user rejected: no",
        approved=False,
        auto_approved=False,
    )
    call = fake.calls[0]
    assert call["success"] is False
    assert call["error_message"] == "user rejected: no"
    assert call["resource"] == "rm -rf /"
    assert call["details"]["approved"] is False


@pytest.mark.asyncio
async def test_resource_slot_uses_most_identifying_arg() -> None:
    fake = _FakeDBLogger()
    logger = AuditLogger(fake)
    await logger.record_tool_call(
        tool="web_fetch",
        user="sven",
        turn_id="t_1",
        tool_call_id="tc_3",
        args={"url": "https://example.com/x"},
        status="ok",
        bytes_out=100,
        error=None,
        approved=True,
        auto_approved=True,
    )
    assert fake.calls[0]["resource"] == "https://example.com/x"


@pytest.mark.asyncio
async def test_resource_slot_falls_back_to_tool_name() -> None:
    fake = _FakeDBLogger()
    logger = AuditLogger(fake)
    await logger.record_tool_call(
        tool="grep",
        user="sven",
        turn_id="t_1",
        tool_call_id="tc_4",
        args={"pattern": "TODO"},
        status="ok",
        bytes_out=42,
        error=None,
        approved=True,
        auto_approved=True,
    )
    # pattern is in the priority list -> resource = "TODO"
    assert fake.calls[0]["resource"] == "TODO"


@pytest.mark.asyncio
async def test_resource_truncates_long_values() -> None:
    fake = _FakeDBLogger()
    logger = AuditLogger(fake)
    long_cmd = "echo " + "x" * 500
    await logger.record_tool_call(
        tool="run_bash",
        user="sven",
        turn_id="t_1",
        tool_call_id="tc_5",
        args={"command": long_cmd},
        status="ok",
        bytes_out=0,
        error=None,
        approved=True,
        auto_approved=False,
    )
    assert len(fake.calls[0]["resource"]) <= 200
```

- [ ] **Step 2: Run and verify they fail**

```bash
pytest plugin/tests/test_audit.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `plugin/services/audit.py`**

```python
"""Audit-log adapter — wraps BaluHost's AuditLoggerDB for tool calls.

``AuditLoggerDB.log_event`` is synchronous and DB-backed. This wrapper
shapes a tool-call record into that method's contract and dispatches it
on a worker thread so the async agent loop never blocks on DB I/O.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

_EVENT_TYPE = "BALU_CODE"
_RESOURCE_MAX = 200


class _DBLoggerProto(Protocol):
    def log_event(
        self,
        *,
        event_type: str,
        user: str | None,
        action: str,
        resource: str | None = None,
        details: dict | None = None,
        success: bool = True,
        error_message: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        db: Any = None,
    ) -> Any: ...


class AuditLogger:
    def __init__(self, db_logger: _DBLoggerProto) -> None:
        self._db = db_logger

    async def record_tool_call(
        self,
        *,
        tool: str,
        user: str,
        turn_id: str,
        tool_call_id: str,
        args: dict,
        status: str,
        bytes_out: int,
        error: str | None,
        approved: bool,
        auto_approved: bool,
    ) -> None:
        resource = _derive_resource(tool, args)
        details = {
            "turn_id": turn_id,
            "tool_call_id": tool_call_id,
            "args": args,
            "bytes_out": bytes_out,
            "approved": approved,
            "auto_approved": auto_approved,
        }
        success = status == "ok"
        await asyncio.to_thread(
            self._db.log_event,
            event_type=_EVENT_TYPE,
            user=user,
            action=f"tool:{tool}",
            resource=resource,
            details=details,
            success=success,
            error_message=error,
        )


def _derive_resource(tool: str, args: dict) -> str:
    for key in ("path", "url", "command", "pattern"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value[:_RESOURCE_MAX]
    return tool[:_RESOURCE_MAX]


__all__ = ["AuditLogger"]
```

- [ ] **Step 4: Run audit tests — verify they pass**

```bash
pytest plugin/tests/test_audit.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Extend `TurnDeps` in `agent_loop.py`**

Open `plugin/services/agent_loop.py`. Add the import near the existing service imports:

```python
from plugin.services.audit import AuditLogger
```

Update `TurnDeps`:

```python
@dataclass
class TurnDeps:
    """Dependencies a turn needs. Mutable only for the config field in tests."""

    ollama: OllamaClient
    tool_registry: ToolRegistry
    project: Project
    repo_map: RepoMap
    rag: RagIndex
    config: BaluCodePluginConfig
    audit_log: AuditLogger
    system_prompt: str = _SYSTEM_PROMPT
    tool_use_prompt: str = _TOOL_USE_PROMPT
```

- [ ] **Step 6: Update `plugin/deps.py`**

Replace `plugin/deps.py` with:

```python
"""Module-level singletons for the balu_code plugin."""

from __future__ import annotations

from plugin.config import BaluCodePluginConfig
from plugin.services.audit import AuditLogger
from plugin.services.index_jobs import IndexJobTracker
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore
from plugin.services.rag_registry import RagRegistry
from plugin.services.tools import ToolRegistry

_store: ProjectStore | None = None
_ollama: OllamaClient | None = None
_rag_registry: RagRegistry | None = None
_index_job_tracker: IndexJobTracker | None = None
_tool_registry: ToolRegistry | None = None
_plugin_config: BaluCodePluginConfig | None = None
_audit_log: AuditLogger | None = None


def set_singletons(
    store: ProjectStore,
    ollama: OllamaClient,
    rag_registry: RagRegistry,
    index_job_tracker: IndexJobTracker,
    tool_registry: ToolRegistry,
    plugin_config: BaluCodePluginConfig,
    audit_log: AuditLogger,
) -> None:
    global _store, _ollama, _rag_registry, _index_job_tracker, _tool_registry, _plugin_config, _audit_log
    _store = store
    _ollama = ollama
    _rag_registry = rag_registry
    _index_job_tracker = index_job_tracker
    _tool_registry = tool_registry
    _plugin_config = plugin_config
    _audit_log = audit_log


def clear_singletons() -> None:
    global _store, _ollama, _rag_registry, _index_job_tracker, _tool_registry, _plugin_config, _audit_log
    _store = None
    _ollama = None
    _rag_registry = None
    _index_job_tracker = None
    _tool_registry = None
    _plugin_config = None
    _audit_log = None


def get_project_store() -> ProjectStore:
    if _store is None:
        raise RuntimeError("balu_code plugin not initialized (ProjectStore missing)")
    return _store


def get_ollama_client() -> OllamaClient:
    if _ollama is None:
        raise RuntimeError("balu_code plugin not initialized (OllamaClient missing)")
    return _ollama


def get_rag_registry() -> RagRegistry:
    if _rag_registry is None:
        raise RuntimeError("balu_code plugin not initialized (RagRegistry missing)")
    return _rag_registry


def get_index_job_tracker() -> IndexJobTracker:
    if _index_job_tracker is None:
        raise RuntimeError("balu_code plugin not initialized (IndexJobTracker missing)")
    return _index_job_tracker


def get_tool_registry() -> ToolRegistry:
    if _tool_registry is None:
        raise RuntimeError("balu_code plugin not initialized (ToolRegistry missing)")
    return _tool_registry


def get_plugin_config() -> BaluCodePluginConfig:
    if _plugin_config is None:
        raise RuntimeError("balu_code plugin not initialized (BaluCodePluginConfig missing)")
    return _plugin_config


def get_audit_log() -> AuditLogger:
    if _audit_log is None:
        raise RuntimeError("balu_code plugin not initialized (AuditLogger missing)")
    return _audit_log


__all__ = [
    "clear_singletons",
    "get_audit_log",
    "get_index_job_tracker",
    "get_ollama_client",
    "get_plugin_config",
    "get_project_store",
    "get_rag_registry",
    "get_tool_registry",
    "set_singletons",
]
```

- [ ] **Step 7: Update `plugin/__init__.py` `on_startup`**

At the top of the file, add:
```python
from app.services.audit import get_audit_logger_db
from plugin.services.audit import AuditLogger
```

Inside `on_startup`, just before the existing `set_singletons(...)` call:
```python
audit_log = AuditLogger(get_audit_logger_db())
```

Extend the `set_singletons(...)` call:
```python
set_singletons(
    store=project_store,
    ollama=ollama_client,
    rag_registry=rag_registry,
    index_job_tracker=index_job_tracker,
    tool_registry=tool_registry,
    plugin_config=plugin_config,
    audit_log=audit_log,
)
```

If the current call is positional, mirror the updated positional order.

- [ ] **Step 8: Update `plugin/tests/test_plugin_lifecycle.py`**

Near the top of the module, add:
```python
class _NoopAuditLogger:
    async def record_tool_call(self, **kwargs) -> None:
        return None
```

Every `set_singletons(...)` invocation in this test file needs `audit_log=_NoopAuditLogger()` added. Add a sibling accessor test modelled on the existing `test_get_ollama_client_returns_singleton`:

```python
def test_get_audit_log_returns_singleton(populated_singletons):
    from plugin.deps import get_audit_log
    assert get_audit_log() is populated_singletons["audit_log"]
```

Adjust the fixture to expose `audit_log` accordingly.

- [ ] **Step 9: Run lifecycle + audit tests**

```bash
pytest plugin/tests/test_audit.py plugin/tests/test_plugin_lifecycle.py -v
```
Expected: green.

- [ ] **Step 10: Run full suite — `test_agent_loop.py` + `test_routes_chat.py` need `audit_log=`**

```bash
pytest -q
```

Add a helper at the top of `test_agent_loop.py`:
```python
class _NoopAuditLogger:
    async def record_tool_call(self, **kwargs) -> None:
        return None
```
Thread it through every `TurnDeps(...)` construction. Same for `test_routes_chat.py` test fixtures.

- [ ] **Step 11: Commit**

```bash
git add plugin/services/audit.py plugin/services/agent_loop.py plugin/deps.py \
        plugin/__init__.py plugin/tests/test_audit.py plugin/tests/test_plugin_lifecycle.py \
        plugin/tests/test_agent_loop.py plugin/tests/test_routes_chat.py
git commit -m "feat(plugin): add AuditLogger + wire it into lifecycle + TurnDeps"
```

---

## Task 10: `run_turn` — approval gate + audit hook + `max_tokens` + per-iteration tokens

First wave of agent-loop surgery. Adds a `TurnContext` dataclass bundling per-turn state (`turn_id`, `cancel_token`, `pending_approvals`, `username`); an approval-gate branch around tool dispatch; an audit-hook after every tool result; the `"max_tokens"` stop-reason fix; and per-iteration token re-accumulation (the 4a carryover).

Cancel-token wiring is **deferred to Task 11**.

**Files:**
- Modify: `plugin/services/agent_loop.py`
- Modify: `plugin/tests/test_agent_loop.py`

- [ ] **Step 1: Verify `count_messages_tokens` exists in the tokenizer module**

```bash
grep -n "def count_messages_tokens" plugin/services/tokenizer.py
```
Expected: one hit. If missing, flag as a 4a regression before continuing.

- [ ] **Step 2: Write the failing tests**

Append to `plugin/tests/test_agent_loop.py`:

```python
class TestApprovalGateAndAudit:
    @pytest.mark.asyncio
    async def test_write_tool_emits_approval_request_and_awaits(
        self, fake_ollama_and_deps, tmp_path
    ):
        """Scripted model: first chat_stream yields a write_file tool_call;
        second chat_stream yields plain text. A helper resolves the
        pending_approvals future mid-turn to Approval(approved=True).
        Assert emitted sequence:
        TurnStart → ToolCall(auto_approved=False) → ApprovalRequest →
        ToolResult(ok) → Token* → TurnEnd(done)."""

    @pytest.mark.asyncio
    async def test_rejected_approval_feeds_error_back(
        self, fake_ollama_and_deps, tmp_path
    ):
        """Same as above but resolve future with Approval(approved=False,
        reason='no'). Assert ToolResult(error='user rejected: no'), loop
        continues, final TurnEnd(done)."""

    @pytest.mark.asyncio
    async def test_audit_logger_called_for_every_tool_result(
        self, fake_ollama_and_deps, tmp_path, fake_audit
    ):
        """A 2-tool turn (e.g. read_file then write_file approved) produces
        exactly 2 audit records with matching tool names + action tags."""


class TestStopReasonMaxTokens:
    @pytest.mark.asyncio
    async def test_token_cap_trip_uses_max_tokens_reason(
        self, fake_ollama_and_deps
    ):
        """Set config.max_total_tokens_per_turn to a small value;
        assert TurnEnd.stop_reason == 'max_tokens' (not 'max_iter')."""


class TestPerIterationTokenReAccumulation:
    @pytest.mark.asyncio
    async def test_messages_tokens_counted_each_iteration(
        self, fake_ollama_and_deps
    ):
        """In a 3-iteration turn the final total_tokens must include the
        per-iteration count of the growing messages list, not only the
        initial context_tokens + assistant content tokens."""
```

Add fixtures at module level:
```python
class _NoopAuditLogger:
    def __init__(self):
        self.calls = []

    async def record_tool_call(self, **kw):
        self.calls.append(kw)


@pytest.fixture
def fake_audit():
    return _NoopAuditLogger()
```

Flesh out the test bodies using the existing `FakeOllama` / helper pattern from the 4a tests — resolve the Approval future on a scheduled task (`asyncio.get_running_loop().call_later(...)`).

- [ ] **Step 3: Run the new tests and watch them fail**

```bash
pytest plugin/tests/test_agent_loop.py -v -k "Approval or StopReason or PerIteration"
```

- [ ] **Step 4: Replace `plugin/services/agent_loop.py`**

```python
"""Main agent-loop runtime."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from balu_code_shared.events import (
    Approval,
    ApprovalRequest,
    Error,
    Event,
    Token,
    ToolCall,
    ToolResult,
    TurnEnd,
    TurnStart,
)
from pydantic import ValidationError

from plugin.config import BaluCodePluginConfig
from plugin.services.audit import AuditLogger
from plugin.services.cancel import CancelToken
from plugin.services.context_assembler import assemble_context
from plugin.services.ollama_client import (
    OllamaClient,
    OllamaRateLimited,
    OllamaTimeoutError,
    OllamaUnreachable,
)
from plugin.services.project_store import Project
from plugin.services.rag_index import RagIndex
from plugin.services.repo_map import RepoMap
from plugin.services.tokenizer import count_messages_tokens, count_tokens
from plugin.services.tools import ToolRegistry
from plugin.services.tools.base import ToolContext

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system.md"
_TOOL_USE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "tool_use.md"

_SYSTEM_PROMPT = _SYSTEM_PROMPT_PATH.read_text()
_TOOL_USE_PROMPT = _TOOL_USE_PROMPT_PATH.read_text()


@dataclass
class TurnDeps:
    ollama: OllamaClient
    tool_registry: ToolRegistry
    project: Project
    repo_map: RepoMap
    rag: RagIndex
    config: BaluCodePluginConfig
    audit_log: AuditLogger
    system_prompt: str = _SYSTEM_PROMPT
    tool_use_prompt: str = _TOOL_USE_PROMPT


@dataclass
class TurnContext:
    turn_id: str
    cancel_token: CancelToken
    pending_approvals: dict[str, asyncio.Future[Approval]]
    username: str


Emitter = Callable[[Event], Awaitable[None]]


def _new_tool_call_id(iteration: int, suffix: int) -> str:
    return f"tc_{iteration}_{suffix}"


async def run_turn(
    user_message: str,
    history: list[dict],
    deps: TurnDeps,
    emit: Emitter,
    ctx: TurnContext,
) -> None:
    """Drive one turn. Appends to ``history`` in place. Never raises."""
    turn_id = ctx.turn_id
    try:
        repo_map_text = await _resolve_repo_map(deps)
    except Exception as e_rm:
        await emit(Error(code="repo_map_failed", message=str(e_rm)))
        await emit(TurnEnd(turn_id=turn_id, total_tokens=0, iterations=0, stop_reason="error"))
        return

    try:
        rag_hits = await deps.rag.search(user_message, top_k=deps.config.rag_top_k)
    except Exception:
        rag_hits = []

    history_snapshot = list(history)
    history.append({"role": "user", "content": user_message})

    try:
        assembled = await assemble_context(
            system_prompt=deps.system_prompt,
            tool_use_prompt=deps.tool_use_prompt,
            repo_map_text=repo_map_text,
            rag_hits=rag_hits,
            history=history[:-1],
            user_message=user_message,
            context_window=deps.config.context_window,
            repo_map_budget=deps.config.repo_map_budget,
            rag_budget=deps.config.rag_budget,
        )
    except Exception as e_ca:
        history[:] = history_snapshot
        await emit(Error(code="context_assembly_failed", message=str(e_ca)))
        await emit(TurnEnd(turn_id=turn_id, total_tokens=0, iterations=0, stop_reason="error"))
        return

    messages = list(assembled.messages)
    await emit(
        TurnStart(
            turn_id=turn_id,
            model=deps.config.chat_model,
            context_tokens=assembled.context_tokens,
        )
    )

    total_tokens = assembled.context_tokens
    iterations = 0
    for _iteration in range(deps.config.max_iterations):
        iterations += 1

        # Per-iteration token re-accumulation (4a carryover).
        total_tokens = assembled.context_tokens + count_messages_tokens(messages)
        if total_tokens > deps.config.max_total_tokens_per_turn:
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="max_tokens",
                )
            )
            return

        buffered_content = ""
        tool_calls_from_stream: list[dict] | None = None

        try:
            async for frame in deps.ollama.chat_stream(
                deps.config.chat_model,
                messages,
                tools=deps.tool_registry.ollama_schemas(),
                options={"temperature": deps.config.temperature},
            ):
                message = frame.get("message") or {}
                content_piece = message.get("content") or ""
                if content_piece:
                    buffered_content += content_piece
                    await emit(Token(content=content_piece))
                maybe_tool_calls = message.get("tool_calls")
                if maybe_tool_calls:
                    tool_calls_from_stream = list(maybe_tool_calls)
                if frame.get("done"):
                    break
        except OllamaUnreachable as e_unr:
            history[:] = history_snapshot
            await emit(Error(code="ollama_unreachable", message=str(e_unr)))
            await emit(TurnEnd(turn_id=turn_id, total_tokens=total_tokens, iterations=iterations, stop_reason="error"))
            return
        except OllamaTimeoutError as e_tm:
            history[:] = history_snapshot
            await emit(Error(code="ollama_timeout", message=str(e_tm)))
            await emit(TurnEnd(turn_id=turn_id, total_tokens=total_tokens, iterations=iterations, stop_reason="error"))
            return
        except OllamaRateLimited as e_rl:
            history[:] = history_snapshot
            await emit(Error(code="ollama_rate_limited", message=str(e_rl)))
            await emit(TurnEnd(turn_id=turn_id, total_tokens=total_tokens, iterations=iterations, stop_reason="error"))
            return
        except Exception as e_gen:
            history[:] = history_snapshot
            await emit(Error(code="internal", message=f"{type(e_gen).__name__}: {e_gen}"))
            await emit(TurnEnd(turn_id=turn_id, total_tokens=total_tokens, iterations=iterations, stop_reason="error"))
            return

        total_tokens += count_tokens(buffered_content)

        if not tool_calls_from_stream:
            history.append({"role": "assistant", "content": buffered_content})
            await emit(TurnEnd(turn_id=turn_id, total_tokens=total_tokens, iterations=iterations, stop_reason="done"))
            return

        assistant_msg: dict = {"role": "assistant", "content": buffered_content}
        assistant_msg["tool_calls"] = tool_calls_from_stream
        history.append(assistant_msg)
        messages.append(assistant_msg)

        tool_ctx = ToolContext(
            project_root=Path(deps.project.root_path),
            project_id=deps.project.id,
            turn_id=turn_id,
            cancel_token=ctx.cancel_token,
        )
        for call_index, call in enumerate(tool_calls_from_stream):
            function = call.get("function") or {}
            name = function.get("name") or ""
            raw_args = function.get("arguments")
            try:
                args_dict = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
            except (json.JSONDecodeError, ValueError):
                args_dict = {}
            tc_id = _new_tool_call_id(iterations, call_index)

            try:
                tool = deps.tool_registry.get(name)
            except KeyError:
                msg = f"unknown tool '{name}'"
                await emit(ToolCall(tool_call_id=tc_id, tool=name, args=args_dict, auto_approved=True))
                await emit(ToolResult(tool_call_id=tc_id, status="error", bytes_out=0, error=msg))
                history.append({"role": "tool", "name": name, "content": f"error: {msg}"})
                messages.append({"role": "tool", "name": name, "content": f"error: {msg}"})
                await deps.audit_log.record_tool_call(
                    tool=name, user=ctx.username, turn_id=turn_id, tool_call_id=tc_id,
                    args=args_dict, status="error", bytes_out=0, error=msg,
                    approved=True, auto_approved=True,
                )
                continue

            auto_approved = tool.risk == "read"
            await emit(ToolCall(tool_call_id=tc_id, tool=name, args=args_dict, auto_approved=auto_approved))

            approved = auto_approved
            if not auto_approved:
                await emit(ApprovalRequest(tool_call_id=tc_id, tool=name, args=args_dict, risk=tool.risk))
                loop = asyncio.get_running_loop()
                future: asyncio.Future[Approval] = loop.create_future()
                ctx.pending_approvals[tc_id] = future
                try:
                    decision = await future
                finally:
                    ctx.pending_approvals.pop(tc_id, None)

                approved = decision.approved
                if not approved:
                    reason = decision.reason or "no reason"
                    msg = f"user rejected: {reason}"
                    await emit(ToolResult(tool_call_id=tc_id, status="error", bytes_out=0, error=msg))
                    tool_msg = {"role": "tool", "name": name, "content": f"error: {msg}"}
                    history.append(tool_msg)
                    messages.append(tool_msg)
                    await deps.audit_log.record_tool_call(
                        tool=name, user=ctx.username, turn_id=turn_id, tool_call_id=tc_id,
                        args=args_dict, status="error", bytes_out=0, error=msg,
                        approved=False, auto_approved=False,
                    )
                    continue

            try:
                parsed = tool.args_schema.model_validate(args_dict)
            except ValidationError as e_val:
                msg = f"invalid args: {e_val}"
                await emit(ToolResult(tool_call_id=tc_id, status="error", bytes_out=0, error=msg))
                tool_msg = {"role": "tool", "name": name, "content": f"error: {msg}"}
                history.append(tool_msg)
                messages.append(tool_msg)
                await deps.audit_log.record_tool_call(
                    tool=name, user=ctx.username, turn_id=turn_id, tool_call_id=tc_id,
                    args=args_dict, status="error", bytes_out=0, error=msg,
                    approved=approved, auto_approved=auto_approved,
                )
                continue

            try:
                result = await tool.execute(parsed, tool_ctx)
            except Exception as e_tool:
                msg = f"{type(e_tool).__name__}: {e_tool}"
                await emit(ToolResult(tool_call_id=tc_id, status="error", bytes_out=0, error=msg))
                tool_msg = {"role": "tool", "name": name, "content": f"error: {msg}"}
                history.append(tool_msg)
                messages.append(tool_msg)
                await deps.audit_log.record_tool_call(
                    tool=name, user=ctx.username, turn_id=turn_id, tool_call_id=tc_id,
                    args=args_dict, status="error", bytes_out=0, error=msg,
                    approved=approved, auto_approved=auto_approved,
                )
                continue

            await emit(
                ToolResult(
                    tool_call_id=tc_id,
                    status=result.status,
                    bytes_out=result.bytes_out,
                    error=result.error,
                )
            )
            tool_msg = {"role": "tool", "name": name, "content": result.text}
            history.append(tool_msg)
            messages.append(tool_msg)
            await deps.audit_log.record_tool_call(
                tool=name, user=ctx.username, turn_id=turn_id, tool_call_id=tc_id,
                args=args_dict, status=result.status, bytes_out=result.bytes_out, error=result.error,
                approved=approved, auto_approved=auto_approved,
            )

    await emit(
        TurnEnd(
            turn_id=turn_id,
            total_tokens=total_tokens,
            iterations=iterations,
            stop_reason="max_iter",
        )
    )


async def _resolve_repo_map(deps: TurnDeps) -> str:
    files = await asyncio.to_thread(deps.repo_map.walk_and_cache)
    rendered = deps.repo_map.render(files, budget_tokens=deps.config.repo_map_budget)
    return rendered.text


__all__ = ["TurnContext", "TurnDeps", "run_turn"]
```

- [ ] **Step 5: Update existing `test_agent_loop.py` harness**

Add a helper:
```python
from plugin.services.agent_loop import TurnContext
from plugin.services.cancel import CancelToken


def _make_ctx(turn_id="t_1", username="sven"):
    return TurnContext(
        turn_id=turn_id,
        cancel_token=CancelToken(),
        pending_approvals={},
        username=username,
    )
```

Update every `await run_turn(...)` call to pass `_make_ctx()` as the fifth arg. Replace the existing signature `run_turn(user_message, history, deps, emit)` → `run_turn(user_message, history, deps, emit, ctx)` everywhere in the tests.

- [ ] **Step 6: Run the full agent-loop test file**

```bash
pytest plugin/tests/test_agent_loop.py -v
```
Expected: new + existing tests green.

- [ ] **Step 7: Run full suite**

```bash
pytest -q
```
Expected: ~310 passed.

- [ ] **Step 8: Commit**

```bash
git add plugin/services/agent_loop.py plugin/tests/test_agent_loop.py
git commit -m "feat(plugin): add approval gate + audit hook + max_tokens stop reason to run_turn"
```

---

## Task 11: `run_turn` — cancel-token integration

Sprinkle `cancel_token.check()` in three spots and wrap the approval-await so a `Cancel` frame from the handler unblocks it.

**Files:**
- Modify: `plugin/services/agent_loop.py`
- Modify: `plugin/tests/test_agent_loop.py`

- [ ] **Step 1: Write the failing tests**

Append to `plugin/tests/test_agent_loop.py`:

```python
class TestCancelToken:
    @pytest.mark.asyncio
    async def test_cancel_between_iterations_ends_turn(self, fake_ollama_and_deps):
        """ctx.cancel_token.cancel() between iterations produces
        TurnEnd(stop_reason='cancelled')."""

    @pytest.mark.asyncio
    async def test_cancel_during_ollama_stream_stops_streaming(self, fake_ollama_and_deps):
        """Flip cancel_token mid-stream; remaining stream chunks do not reach
        emit. TurnEnd(cancelled) emitted."""

    @pytest.mark.asyncio
    async def test_cancel_while_awaiting_approval_ends_turn(self, fake_ollama_and_deps):
        """Set up pending_approvals future, call cancel_token.cancel() +
        pending_approvals[tc_id].cancel() from a sibling task. run_turn
        produces TurnEnd(cancelled)."""
```

Flesh out the bodies using `TurnContext` + `asyncio.create_task` helpers.

- [ ] **Step 2: Run and verify they fail**

```bash
pytest plugin/tests/test_agent_loop.py -v -k "TestCancelToken"
```

- [ ] **Step 3: Add cancel-checks to `run_turn`**

Open `plugin/services/agent_loop.py`. Four surgical edits:

**Point 1 — inside the iteration loop, right after the `max_tokens` early-return block:**
```python
        try:
            ctx.cancel_token.check()
        except asyncio.CancelledError:
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="cancelled",
                )
            )
            return
```

**Point 2 — inside `async for frame in deps.ollama.chat_stream(...)`, first statement in the loop body:**
```python
            async for frame in deps.ollama.chat_stream(...):
                try:
                    ctx.cancel_token.check()
                except asyncio.CancelledError:
                    await emit(
                        TurnEnd(
                            turn_id=turn_id,
                            total_tokens=total_tokens,
                            iterations=iterations,
                            stop_reason="cancelled",
                        )
                    )
                    return
                message = frame.get("message") or {}
                ...
```

**Point 3 — first statement inside `for call_index, call in enumerate(tool_calls_from_stream):`:**
```python
        for call_index, call in enumerate(tool_calls_from_stream):
            try:
                ctx.cancel_token.check()
            except asyncio.CancelledError:
                await emit(
                    TurnEnd(
                        turn_id=turn_id,
                        total_tokens=total_tokens,
                        iterations=iterations,
                        stop_reason="cancelled",
                    )
                )
                return
            function = call.get("function") or {}
            ...
```

**Point 4 — replace the approval-await `try/finally` block:**

From:
```python
                try:
                    decision = await future
                finally:
                    ctx.pending_approvals.pop(tc_id, None)
```

To:
```python
                try:
                    decision = await future
                except asyncio.CancelledError:
                    ctx.pending_approvals.pop(tc_id, None)
                    await emit(
                        TurnEnd(
                            turn_id=turn_id,
                            total_tokens=total_tokens,
                            iterations=iterations,
                            stop_reason="cancelled",
                        )
                    )
                    return
                finally:
                    ctx.pending_approvals.pop(tc_id, None)
```

- [ ] **Step 4: Run cancel tests — verify they pass**

```bash
pytest plugin/tests/test_agent_loop.py -v -k "TestCancelToken"
```
Expected: 3 passed.

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```
Expected: ~313 passed.

- [ ] **Step 6: Commit**

```bash
git add plugin/services/agent_loop.py plugin/tests/test_agent_loop.py
git commit -m "feat(plugin): wire cancel-token checks into run_turn (stream + tool + approval)"
```

---

## Task 12: WS `/chat` handler — `pending_approvals` + `Cancel`/`Approval` routing

Rewrite the receive loop so it dispatches three frame types. Drops the `_user` underscore so `username` flows into `TurnContext`.

**Files:**
- Modify: `plugin/routes.py`
- Modify: `plugin/tests/test_routes_chat.py` (minor updates; new scenarios in Task 14)

- [ ] **Step 1: Skim the existing test harness**

```bash
grep -n "FakeOllama\|TestClient\|websocket_connect\|TurnDeps\|set_singletons\|UserPublic" plugin/tests/test_routes_chat.py | head -40
```

Identify the existing fake-Ollama, the dependency-override fixture, and which attribute of `UserPublic` gives a username.

- [ ] **Step 2: Verify `UserPublic` has a `username` field**

```bash
grep -n "class UserPublic" /opt/baluhost/backend/app/schemas/user.py
grep -n "username\|email" /opt/baluhost/backend/app/schemas/user.py | head
```

If the field is named differently (e.g. `email`), substitute that name in the handler below.

- [ ] **Step 3: Replace the `chat_socket` handler**

Open `plugin/routes.py`. Add to the top-of-file imports:

```python
import uuid as _uuid

from balu_code_shared.events import (
    Approval,
    ApprovalRequest,
    Cancel,
    Error,
    TurnEnd,
    TurnStart,
    UserMessage,
    parse_frame,
)

from plugin.deps import (
    get_audit_log,
    get_index_job_tracker,
    get_ollama_client,
    get_plugin_config,
    get_project_store,
    get_rag_registry,
    get_tool_registry,
)
from plugin.services.agent_loop import TurnContext, TurnDeps, run_turn
from plugin.services.audit import AuditLogger
from plugin.services.cancel import CancelToken
```

Replace the `chat_socket` function body with:

```python
    @router.websocket("/chat")
    async def chat_socket(
        websocket: WebSocket,
        project_id: int,
        user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
        ollama: OllamaClient = Depends(get_ollama_client),
        rag_registry: RagRegistry = Depends(get_rag_registry),
        tool_registry: ToolRegistry = Depends(get_tool_registry),
        config: BaluCodePluginConfig = Depends(get_plugin_config),
        audit_log: AuditLogger = Depends(get_audit_log),
    ) -> None:
        try:
            project = await asyncio.to_thread(store.get_project, project_id)
        except ProjectNotFoundError:
            await websocket.close(code=1008, reason="project not found")
            return

        try:
            rag = await rag_registry.get(project.id)
        except Exception as e_rag:
            await websocket.close(code=1011, reason=f"rag init failed: {e_rag}")
            return

        repo_map = RepoMap(
            project_root=Path(project.root_path),
            store=store,
            project_id=project.id,
        )

        await websocket.accept()

        deps = TurnDeps(
            ollama=ollama,
            tool_registry=tool_registry,
            project=project,
            repo_map=repo_map,
            rag=rag,
            config=config,
            audit_log=audit_log,
        )
        history: list[dict] = []
        pending_approvals: dict[str, asyncio.Future[Approval]] = {}
        current_cancel: CancelToken | None = None
        current_turn_id: str | None = None

        async def _emit(event) -> None:
            await websocket.send_json(event.model_dump())

        try:
            while True:
                raw = await websocket.receive_json()
                try:
                    frame = parse_frame(raw)
                except ValidationError as e_val:
                    await _emit(Error(code="bad_frame", message=str(e_val)[:200]))
                    continue

                if isinstance(frame, UserMessage):
                    if current_cancel is not None:
                        await _emit(Error(code="turn_in_flight", message="a turn is already running"))
                        continue
                    current_cancel = CancelToken()
                    current_turn_id = f"t_{_uuid.uuid4().hex[:12]}"
                    ctx = TurnContext(
                        turn_id=current_turn_id,
                        cancel_token=current_cancel,
                        pending_approvals=pending_approvals,
                        username=user.username,
                    )
                    try:
                        await run_turn(frame.content, history, deps, _emit, ctx)
                    finally:
                        current_cancel = None
                        current_turn_id = None
                        pending_approvals.clear()
                    continue

                if isinstance(frame, Approval):
                    fut = pending_approvals.pop(frame.tool_call_id, None)
                    if fut is None:
                        await _emit(Error(
                            code="unknown_approval",
                            message=f"no pending request for {frame.tool_call_id}",
                        ))
                    elif not fut.done():
                        fut.set_result(frame)
                    continue

                if isinstance(frame, Cancel):
                    if current_cancel is None or frame.turn_id != current_turn_id:
                        await _emit(Error(code="no_turn_to_cancel", message="no matching turn in flight"))
                        continue
                    current_cancel.cancel()
                    for fut in list(pending_approvals.values()):
                        if not fut.done():
                            fut.cancel()
                    continue

                await _emit(Error(
                    code="unsupported_frame",
                    message=f"frame type '{frame.type}' is not supported",
                ))
        except WebSocketDisconnect:
            if current_cancel is not None:
                current_cancel.cancel()
            return
```

- [ ] **Step 4: Run existing chat tests — happy path must still pass**

```bash
pytest plugin/tests/test_routes_chat.py -v
```
Expected: 4a happy-path tests still green.

- [ ] **Step 5: Commit**

```bash
git add plugin/routes.py plugin/tests/test_routes_chat.py
git commit -m "feat(plugin): add pending_approvals + Cancel/Approval routing to WS /chat"
```

---

## Task 13: Register the four new tools in `default_registry()`

**Files:**
- Modify: `plugin/services/tools/__init__.py`
- Modify: `plugin/tests/test_tool_base.py`

- [ ] **Step 1: Write the failing test**

Append to `plugin/tests/test_tool_base.py`:

```python
def test_default_registry_includes_all_seven_tools():
    from plugin.services.tools import default_registry

    reg = default_registry()
    assert set(reg.names()) == {
        "read_file",
        "glob",
        "grep",
        "write_file",
        "apply_patch",
        "run_bash",
        "web_fetch",
    }


def test_default_registry_schemas_include_write_and_exec():
    from plugin.services.tools import default_registry

    reg = default_registry()
    schemas = reg.ollama_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert {"write_file", "apply_patch", "run_bash", "web_fetch"}.issubset(names)
```

- [ ] **Step 2: Run and verify they fail**

```bash
pytest plugin/tests/test_tool_base.py -v -k "default_registry"
```

- [ ] **Step 3: Update `plugin/services/tools/__init__.py`**

Replace the file with:

```python
"""Tool registry + Phase-4a/4b convenience exports."""

from __future__ import annotations

from plugin.services.tools.apply_patch import ApplyPatchTool
from plugin.services.tools.base import Tool, ToolContext, ToolResult
from plugin.services.tools.glob_tool import GlobTool
from plugin.services.tools.grep_tool import GrepTool
from plugin.services.tools.read_file import ReadFileTool
from plugin.services.tools.run_bash import RunBashTool
from plugin.services.tools.web_fetch import WebFetchTool
from plugin.services.tools.write_file import WriteFileTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def ollama_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.args_schema.model_json_schema(),
                },
            }
            for t in self._tools.values()
        ]


def default_registry() -> ToolRegistry:
    """Return a ToolRegistry pre-populated with every shipped tool."""
    reg = ToolRegistry()
    reg.register(ReadFileTool())
    reg.register(GlobTool())
    reg.register(GrepTool())
    reg.register(WriteFileTool())
    reg.register(ApplyPatchTool())
    reg.register(RunBashTool())
    reg.register(WebFetchTool())
    return reg


__all__ = [
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "default_registry",
]
```

- [ ] **Step 4: Run tool-registry tests**

```bash
pytest plugin/tests/test_tool_base.py -v -k "default_registry"
```
Expected: 2 passed.

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add plugin/services/tools/__init__.py plugin/tests/test_tool_base.py
git commit -m "feat(plugin): register write_file/apply_patch/run_bash/web_fetch in default_registry"
```

---

## Task 14: End-to-end approval + cancel tests over WS `/chat`

**Files:**
- Modify: `plugin/tests/test_routes_chat.py`

- [ ] **Step 1: Add the five new E2E tests**

Append to `plugin/tests/test_routes_chat.py`:

```python
class TestApprovalFlowE2E:
    def test_approval_approved_dispatches_tool_and_audits(
        self, client_with_project, fake_audit
    ):
        """Scripted FakeOllama: first chat_stream yields a write_file tool_call;
        second yields plain text. Flow:
          client → UserMessage
          server → TurnStart
          server → ToolCall(auto_approved=False) + ApprovalRequest
          client → Approval(approved=True)
          server → ToolResult(ok) + Token(s) + TurnEnd(done)
        Assertions:
          - emitted frame sequence matches above
          - fake_audit.calls has exactly 1 record with
            event-action 'tool:write_file', success=True.
        """

    def test_approval_rejected_feeds_error_back_and_audits_rejection(
        self, client_with_project, fake_audit
    ):
        """Same setup but client sends Approval(approved=False, reason='no').
        Assertions:
          - ToolResult(error='user rejected: no')
          - loop continues, second iteration produces plain text → TurnEnd(done)
          - fake_audit.calls has 1 record with success=False,
            error_message='user rejected: no', approved=False."""

    def test_unknown_approval_returns_error_frame(self, client_with_project):
        """Send Approval(tool_call_id='bogus') with no turn in flight;
        expect Error(code='unknown_approval')."""


class TestCancelFlowE2E:
    def test_cancel_between_iterations_ends_turn_cancelled(
        self, client_with_project, fake_audit
    ):
        """FakeOllama scripted to emit a read_file tool_call per iteration
        indefinitely; test opens the WS, sends UserMessage, waits for the
        first ToolResult, sends Cancel(turn_id=<observed_turn_id>).
        Server emits TurnEnd(stop_reason='cancelled')."""

    def test_cancel_wrong_turn_id_returns_error(self, client_with_project):
        """No turn in flight → Cancel(turn_id='bogus') produces
        Error(code='no_turn_to_cancel')."""
```

Flesh out the bodies using the Phase-4a `FakeOllama` + `TestClient` fixtures. Each test opens a WS, sends `user_message`, collects frames, sends an `approval`/`cancel` mid-flow, and asserts the final sequence. Add a `fake_audit` fixture mirroring the one from `test_agent_loop.py`:

```python
class _NoopAuditLogger:
    def __init__(self):
        self.calls = []

    async def record_tool_call(self, **kw):
        self.calls.append(kw)


@pytest.fixture
def fake_audit(app):
    logger = _NoopAuditLogger()
    from plugin.deps import get_audit_log
    app.dependency_overrides[get_audit_log] = lambda: logger
    yield logger
    app.dependency_overrides.pop(get_audit_log, None)
```

- [ ] **Step 2: Run the new E2E tests**

```bash
pytest plugin/tests/test_routes_chat.py -v -k "Approval or Cancel"
```

Expect failures while filling in bodies; iterate until all 5 pass.

- [ ] **Step 3: Run full suite**

```bash
pytest -q
```
Expected: ~320 passed.

- [ ] **Step 4: Commit**

```bash
git add plugin/tests/test_routes_chat.py
git commit -m "test(plugin): add E2E approval + cancel tests over WS /chat"
```

---

## Task 15: Phase 4b verification + push

**Files:**
- Create: `docs/phase-4b-verification.md`

- [ ] **Step 1: Full local CI equivalent**

```bash
source .venv/bin/activate
ruff check .
ruff format --check .
pytest -v
rm -rf dist/
python -m scripts.build_bhplugin --repo-root . --dist dist/
python -m scripts.build_wheel --repo-root . --dist dist/
ls dist/
```

Expected:
- ruff: clean.
- pytest: record actual count (≥ 248 + ~60 new ≈ 310).
- `dist/` has `balu_code-0.1.0.bhplugin`, `.sha256`, `balu_code_cli-0.1.0-py3-none-any.whl`.

- [ ] **Step 2: Verify `.bhplugin` includes the Phase-4b modules**

```bash
python -c "
import zipfile
with zipfile.ZipFile('dist/balu_code-0.1.0.bhplugin') as zf:
    names = sorted(zf.namelist())
want = {
    'services/paths.py',
    'services/cancel.py',
    'services/audit.py',
    'services/tools/write_file.py',
    'services/tools/apply_patch.py',
    'services/tools/run_bash.py',
    'services/tools/web_fetch.py',
}
missing = want - set(names)
assert not missing, f'missing: {missing}'
print('ok', len(names), 'files')
"
```
Expected: `ok <N> files`.

- [ ] **Step 3: Smoke-check `AuditLoggerDB` import path resolves inside BaluHost's venv**

```bash
/opt/baluhost/venv/bin/python -c "from app.services.audit import get_audit_logger_db; print(get_audit_logger_db())"
```
Expected: prints `<AuditLoggerDB ...>` — proves the import path used by `plugin/__init__.py` resolves.

- [ ] **Step 4: Create `docs/phase-4b-verification.md`**

```markdown
# Phase 4b verification — 2026-04-19

## Environment (local dev)

- Commit: `<git rev-parse --short HEAD>`
- Python: 3.13.5 (CI matrix covers 3.11 & 3.12)

## Automated checks

- [x] `ruff check .` — clean
- [x] `ruff format --check .` — clean
- [x] `pytest -v` — `<N>` tests passing
- [x] `.bhplugin` includes all Phase-4b service + tool modules
- [x] `python -m scripts.build_wheel` still produces the CLI wheel
- [ ] GitHub Actions: CI green on `main` (fill in after push)

## Manual checks against dev BaluHost

- [ ] Re-sideload the new `.bhplugin`; BaluHost venv installs `unidiff` + `trafilatura`.
- [ ] Restart the BaluHost backend; inspect logs — no ImportError on
      `from app.services.audit import get_audit_logger_db`.
- [ ] Open WS `/chat`; send a `user_message` that triggers `write_file`;
      confirm server emits `approval_request`; reply with
      `approval(approved=true)`; confirm `tool_result(ok)` and a new
      `audit_log` row in the DB with `event_type='BALU_CODE'`,
      `action='tool:write_file'`.
- [ ] Reject a request: reply `approval(approved=false, reason='no')`;
      confirm server emits `tool_result(error='user rejected: no')` and
      the loop continues with a follow-up model turn.
- [ ] Start a long-running turn (ask the model to invoke `run_bash` with
      `sleep 30`); send `cancel(turn_id=...)`; confirm
      `turn_end(cancelled)` and that the subprocess was killed (`ps` on
      the server).
- [ ] Open the BaluHost Audit page — recent entries include `BALU_CODE`
      events with the correct resource field (path/command/url).
```

Fill in actual values. Leave unchecked boxes until the manual checks are done.

- [ ] **Step 5: Push + CI**

```bash
git add docs/phase-4b-verification.md
git commit -m "docs: add Phase 4b verification checklist"
git push origin main
```

Wait for GitHub Actions; confirm matrix green on 3.11 and 3.12:
```bash
gh run list --limit 1
```

- [ ] **Step 6: Link the CI run**

```bash
gh run view --json url --jq .url
# → tick the CI-green box in docs/phase-4b-verification.md and paste the URL
git add docs/phase-4b-verification.md
git commit -m "docs: link Phase 4b CI run (green) in verification checklist"
git push origin main
```

---

## Self-review (coverage against spec)

- **Spec §1 — Architecture & Scope:** covered by Tasks 1–15.
- **Spec §2 — Protocol extensions (`ApprovalRequest`, `Approval`, `Cancel`, `max_tokens`):** Task 2.
- **Spec §3 — Tool specs (`write_file`/`apply_patch`/`run_bash`/`web_fetch`):** Tasks 5, 6, 7, 8. `resolve_within_project` helper in Task 3.
- **Spec §4.A — Approval gate:** Task 10.
- **Spec §4.B — Cancel token:** Tasks 4 (primitive) + 11 (loop wiring) + 7 (subprocess-kill in `run_bash`).
- **Spec §4.C — Audit hook:** Tasks 9 (wrapper) + 10 (emit-site).
- **Spec §4.D — Tool protocol extension:** Task 4 extends `ToolContext` with `cancel_token` instead of changing `Tool.execute`'s signature — smaller blast radius, same functional outcome.
- **Spec §4.E — 4a carryovers:** Task 10 (`max_tokens` + per-iteration token re-accumulation) + Task 3 (paths.py extraction).
- **Spec §5 — WS handler changes:** Task 12.
- **Spec §6 — Tests & rollout:** Tasks 5–8 (tool tests), Task 3 (paths), Task 4 (cancel), Task 9 (audit), Tasks 10–11 (run_turn), Task 14 (E2E). New deps in Task 1. Rollout steps map 1-1 with this plan's tasks.
