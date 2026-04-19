# Balu Code — Phase 4a: Reader-only Agent Loop + WS /chat

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first end-to-end agent turn: `UserMessage` over WebSocket → context assembly → Ollama stream → optional `read_file`/`glob`/`grep` tool dispatch with auto-approval → final assistant tokens → `TurnEnd`. All plumbing for Phase 4b's write/run-shell tools is in place.

**Architecture:** The WS handler owns per-connection history (`list[dict]`). Each `UserMessage` triggers `run_turn` in `plugin/services/agent_loop.py`: context assembled by `context_assembler.py` (budget-trimmed via tiktoken), streamed from Ollama via the existing `chat_stream`, tool calls parsed from the `message.tool_calls` field and dispatched through a Protocol-based `ToolRegistry`. Tools auto-approve for `risk="read"` in 4a; approval-gate machinery lands in 4b.

**Tech Stack:** Python 3.11+, FastAPI (WebSockets), Pydantic v2, `tiktoken>=0.6`, existing httpx + sqlite-vec + tree-sitter stack.

**Parent spec:** [`docs/superpowers/specs/2026-04-19-balu-code-phase-4a-agent-loop-design.md`](../specs/2026-04-19-balu-code-phase-4a-agent-loop-design.md)

---

## File Structure (this phase)

```
Balu_Code/
├── plugin/
│   ├── plugin.json                         [mod (Task 1)]
│   ├── requirements.txt                    [mod (Task 1)]
│   ├── pyproject.toml                      [mod (Task 1)]
│   ├── config.py                           [mod (Task 4)]
│   ├── deps.py                             [mod (Task 12)]
│   ├── __init__.py                         [mod (Task 12)]
│   ├── routes.py                           [mod (Task 13)]
│   ├── prompts/
│   │   ├── system.md                       [new (Task 10)]
│   │   └── tool_use.md                     [new (Task 10)]
│   ├── services/
│   │   ├── tokenizer.py                    [new (Task 2)]
│   │   ├── context_assembler.py            [new (Task 9)]
│   │   ├── agent_loop.py                   [new (Task 11)]
│   │   └── tools/
│   │       ├── __init__.py                 [new (Task 5, extended Task 8)]
│   │       ├── base.py                     [new (Task 5)]
│   │       ├── read_file.py                [new (Task 6)]
│   │       ├── glob_tool.py                [new (Task 7)]
│   │       └── grep_tool.py                [new (Task 8)]
│   └── tests/
│       ├── test_tokenizer.py               [new (Task 2)]
│       ├── test_tool_base.py               [new (Task 5)]
│       ├── test_tool_read_file.py          [new (Task 6)]
│       ├── test_tool_glob.py               [new (Task 7)]
│       ├── test_tool_grep.py               [new (Task 8)]
│       ├── test_context_assembler.py       [new (Task 9)]
│       ├── test_agent_loop.py              [new (Task 11)]
│       ├── test_plugin_lifecycle.py        [mod (Task 12)]
│       └── test_routes_chat.py             [new (Task 13)]
└── shared/
    ├── src/balu_code_shared/events.py      [mod (Task 3)]
    └── tests/test_events.py                [mod (Task 3)]
```

Task 14 is end-of-phase verification.

---

## Task 1: Add `tiktoken` dependency

**Files:**
- Modify: `plugin/plugin.json`
- Modify: `plugin/requirements.txt`
- Modify: `plugin/pyproject.toml`

- [ ] **Step 1: Update `plugin/plugin.json`** — extend `python_requirements`:

Current:
```json
  "python_requirements": [
    "httpx>=0.27",
    "pydantic>=2.6",
    "sqlite-vec>=0.1.9",
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
    "tree-sitter>=0.22",
    "tree-sitter-python>=0.21"
  ],
```

- [ ] **Step 2: Update `plugin/requirements.txt`** — insert `tiktoken>=0.6` alphabetically:

```
httpx>=0.27
pydantic>=2.6
sqlite-vec>=0.1.9
tiktoken>=0.6
tree-sitter>=0.22
tree-sitter-python>=0.21
```

- [ ] **Step 3: Update `plugin/pyproject.toml`** — extend `[project] dependencies`:

```toml
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.6",
  "sqlite-vec>=0.1.9",
  "tiktoken>=0.6",
  "tree-sitter>=0.22",
  "tree-sitter-python>=0.21",
  "fastapi>=0.110",
  "balu-code-shared",
]
```

- [ ] **Step 4: Install dev deps + smoke-test**

```bash
source .venv/bin/activate
pip install -e "plugin[dev]"
python -c "import tiktoken; enc = tiktoken.get_encoding('cl100k_base'); print('ok', len(enc.encode('hello world')))"
```
Expected: `ok 2` (the string "hello world" tokenises to 2 tokens with cl100k_base).

- [ ] **Step 5: Run existing suite — no regression**

```bash
ruff check .
pytest
```
Expected: 194 passed, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add plugin/plugin.json plugin/requirements.txt plugin/pyproject.toml
git commit -m "build(plugin): add tiktoken dependency"
```

---

## Task 2: `tokenizer.py`

**Files:**
- Create: `plugin/services/tokenizer.py`
- Create: `plugin/tests/test_tokenizer.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_tokenizer.py`:

```python
"""Tests for tokenizer helpers."""
from __future__ import annotations

from plugin.services.tokenizer import count_messages_tokens, count_tokens


def test_count_tokens_empty_string_is_zero():
    assert count_tokens("") == 0


def test_count_tokens_hello_world_is_positive():
    assert count_tokens("hello world") > 0


def test_count_tokens_longer_text_is_larger():
    short = count_tokens("hi")
    long = count_tokens("this is a substantially longer sentence with many tokens")
    assert long > short


def test_count_messages_tokens_sums_content():
    messages = [
        {"role": "system", "content": "you are a helpful assistant"},
        {"role": "user", "content": "hello"},
    ]
    total = count_messages_tokens(messages)
    sys_only = count_tokens("you are a helpful assistant")
    user_only = count_tokens("hello")
    # Overhead per message is positive; total must exceed raw content tokens.
    assert total > sys_only + user_only


def test_count_messages_tokens_empty_list_is_zero():
    assert count_messages_tokens([]) == 0


def test_count_messages_tokens_handles_tool_calls():
    messages = [
        {
            "role": "assistant",
            "content": "calling a tool",
            "tool_calls": [
                {"function": {"name": "read_file", "arguments": {"path": "a.py"}}}
            ],
        }
    ]
    total = count_messages_tokens(messages)
    # tool_calls arguments contribute tokens beyond the raw content.
    content_only = count_messages_tokens([{"role": "assistant", "content": "calling a tool"}])
    assert total > content_only
```

- [ ] **Step 2: Run and verify it fails**

```bash
pytest plugin/tests/test_tokenizer.py -v
```
Expected: `ModuleNotFoundError: No module named 'plugin.services.tokenizer'`.

- [ ] **Step 3: Implement `plugin/services/tokenizer.py`**

```python
"""Token counting via tiktoken's cl100k_base encoder.

The encoder is a reasonable default for the models we target
(qwen2.5-coder, llama3.1+, mistral-large, deepseek-coder). Expect
~10-15 percent error against the model's native tokenizer; the
agent loop carries a safety margin (``max_total_tokens_per_turn``)
that absorbs the drift.
"""
from __future__ import annotations

import json
from functools import lru_cache

import tiktoken

_MESSAGE_OVERHEAD = 4  # approximate fixed cost for role+content framing


@lru_cache(maxsize=1)
def _get_encoder() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_get_encoder().encode(text))


def count_messages_tokens(messages: list[dict]) -> int:
    if not messages:
        return 0
    total = 0
    for msg in messages:
        total += _MESSAGE_OVERHEAD
        content = msg.get("content") or ""
        if content:
            total += count_tokens(content)
        tool_calls = msg.get("tool_calls") or []
        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments")
            args_str = args if isinstance(args, str) else json.dumps(args or {})
            total += count_tokens(name) + count_tokens(args_str)
    return total


__all__ = ["count_messages_tokens", "count_tokens"]
```

- [ ] **Step 4: Run and verify**

```bash
pytest plugin/tests/test_tokenizer.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Full suite + ruff**

```bash
ruff check .
pytest
```
Expected: 200 passed.

- [ ] **Step 6: Commit**

```bash
git add plugin/services/tokenizer.py plugin/tests/test_tokenizer.py
git commit -m "feat(plugin): add tokenizer (tiktoken cl100k_base + messages overhead)"
```

---

## Task 3: `shared/events.py` — `ToolCall` + `ToolResult`

**Files:**
- Modify: `shared/src/balu_code_shared/events.py`
- Modify: `shared/tests/test_events.py`

- [ ] **Step 1: Append failing tests to `shared/tests/test_events.py`**

Add to the end of the file:

```python
class TestToolCall:
    def test_constructs_with_all_fields(self):
        from balu_code_shared.events import ToolCall

        evt = ToolCall(
            tool_call_id="tc_01",
            tool="read_file",
            args={"path": "foo.py"},
            auto_approved=True,
        )
        assert evt.type == "tool_call"
        assert evt.tool_call_id == "tc_01"
        assert evt.tool == "read_file"
        assert evt.args == {"path": "foo.py"}
        assert evt.auto_approved is True

    def test_rejects_empty_tool_call_id(self):
        import pytest
        from balu_code_shared.events import ToolCall
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ToolCall(tool_call_id="", tool="t", args={}, auto_approved=True)


class TestToolResult:
    def test_constructs_with_all_fields(self):
        from balu_code_shared.events import ToolResult

        evt = ToolResult(
            tool_call_id="tc_01",
            status="ok",
            bytes_out=42,
        )
        assert evt.type == "tool_result"
        assert evt.tool_call_id == "tc_01"
        assert evt.status == "ok"
        assert evt.bytes_out == 42
        assert evt.error is None

    def test_rejects_unknown_status(self):
        import pytest
        from balu_code_shared.events import ToolResult
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ToolResult(tool_call_id="tc_01", status="pending", bytes_out=0)

    def test_error_carries_message(self):
        from balu_code_shared.events import ToolResult

        evt = ToolResult(
            tool_call_id="tc_01",
            status="error",
            bytes_out=0,
            error="path escapes project root",
        )
        assert evt.status == "error"
        assert evt.error == "path escapes project root"


class TestParseFrameExtended:
    def test_parses_tool_call(self):
        from balu_code_shared.events import ToolCall, parse_frame

        evt = parse_frame(
            {
                "type": "tool_call",
                "tool_call_id": "tc_1",
                "tool": "glob",
                "args": {"pattern": "**/*.py"},
                "auto_approved": True,
            }
        )
        assert isinstance(evt, ToolCall)

    def test_parses_tool_result(self):
        from balu_code_shared.events import ToolResult, parse_frame

        evt = parse_frame(
            {
                "type": "tool_result",
                "tool_call_id": "tc_1",
                "status": "ok",
                "bytes_out": 10,
            }
        )
        assert isinstance(evt, ToolResult)
```

Also update the existing `test_event_union_includes_all_five` test. Find it at the end of the file and replace with:

```python
def test_event_union_includes_all_seven():
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
    }
```

- [ ] **Step 2: Run and verify failure**

```bash
source .venv/bin/activate
pytest shared/tests/test_events.py -v
```
Expected: `ImportError: cannot import name 'ToolCall' from 'balu_code_shared.events'` and similar.

- [ ] **Step 3: Extend `shared/src/balu_code_shared/events.py`**

Find the current class definitions (UserMessage, TurnStart, Token, TurnEnd, Error). Append TWO new classes after `Error`:

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

Find the existing `Event = Annotated[...]` line. Extend the Union to include both new classes:

```python
Event = Annotated[
    UserMessage | TurnStart | Token | TurnEnd | Error | ToolCall | ToolResult,
    Field(discriminator="type"),
]
```

Find `__all__` and extend alphabetically:

```python
__all__ = [
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

- [ ] **Step 4: Run and verify pass**

```bash
pytest shared/tests/test_events.py -v
```
Expected: 21 passed (14 original + 7 new — the renamed union test counts once, and the old "5 members" assertion is now the "7 members" assertion).

- [ ] **Step 5: Full suite + ruff**

```bash
ruff check .
pytest
```
Expected: the full suite grows by the new shared tests (roughly 7 new).

- [ ] **Step 6: Commit**

```bash
git add shared/src/balu_code_shared/events.py shared/tests/test_events.py
git commit -m "feat(shared): add ToolCall and ToolResult WS envelopes"
```

---

## Task 4: `config.py` — 7 new fields

**Files:**
- Modify: `plugin/config.py`
- Modify: `plugin/tests/test_config.py`

- [ ] **Step 1: Append failing tests to `plugin/tests/test_config.py`**

Add at the end of the file:

```python
def test_defaults_for_phase_4a_fields():
    c = BaluCodePluginConfig()
    assert c.context_window == 32768
    assert c.repo_map_budget == 6144
    assert c.rag_budget == 4096
    assert c.rag_top_k == 8
    assert c.max_iterations == 12
    assert c.max_total_tokens_per_turn == 80000
    assert c.temperature == 0.2


def test_temperature_rejects_out_of_range():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BaluCodePluginConfig(temperature=-0.1)
    with pytest.raises(ValidationError):
        BaluCodePluginConfig(temperature=2.5)
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest plugin/tests/test_config.py -v
```
Expected: 2 failures (AttributeError on `context_window`, etc.).

- [ ] **Step 3: Extend `plugin/config.py`**

Find the current `class BaluCodePluginConfig` block. Extend it so it looks like:

```python
class BaluCodePluginConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ollama_base_url: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen2.5-coder:14b-instruct-q4_K_M"
    embed_model: str = "nomic-embed-text"

    # Phase 4a agent-loop knobs
    context_window: int = 32768
    repo_map_budget: int = 6144
    rag_budget: int = 4096
    rag_top_k: int = 8
    max_iterations: int = 12
    max_total_tokens_per_turn: int = 80000
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
```

You also need to import `Field` from pydantic. Find the existing `from pydantic import BaseModel, ConfigDict` line and extend to `from pydantic import BaseModel, ConfigDict, Field`.

- [ ] **Step 4: Run and verify**

```bash
pytest plugin/tests/test_config.py -v
```
Expected: 5 passed (3 existing + 2 new).

- [ ] **Step 5: Full suite + ruff**

```bash
ruff check .
pytest
```
Expected: full suite grows by 2.

- [ ] **Step 6: Commit**

```bash
git add plugin/config.py plugin/tests/test_config.py
git commit -m "feat(plugin): add 7 agent-loop config fields to BaluCodePluginConfig"
```

---

## Task 5: `services/tools/base.py` + `services/tools/__init__.py` — Tool Protocol + ToolRegistry

**Files:**
- Create: `plugin/services/tools/__init__.py`
- Create: `plugin/services/tools/base.py`
- Create: `plugin/tests/test_tool_base.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_tool_base.py`:

```python
"""Tests for Tool Protocol + ToolRegistry."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from plugin.services.tools import ToolRegistry
from plugin.services.tools.base import ToolContext, ToolResult


class _EchoArgs(BaseModel):
    message: str


class _EchoTool:
    name = "echo"
    description = "Echo the message back."
    args_schema = _EchoArgs
    risk = "read"

    async def execute(self, args: _EchoArgs, ctx: ToolContext) -> ToolResult:
        return ToolResult(status="ok", text=args.message, bytes_out=len(args.message))


def test_register_and_get_tool():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    t = reg.get("echo")
    assert t.name == "echo"


def test_get_unknown_tool_raises_key_error():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.get("does_not_exist")


def test_register_duplicate_raises():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    with pytest.raises(ValueError):
        reg.register(_EchoTool())


def test_names_returns_registered_tool_names():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    assert reg.names() == ["echo"]


def test_ollama_schemas_shape():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    schemas = reg.ollama_schemas()
    assert len(schemas) == 1
    s = schemas[0]
    assert s["type"] == "function"
    assert s["function"]["name"] == "echo"
    assert s["function"]["description"] == "Echo the message back."
    params = s["function"]["parameters"]
    assert params["type"] == "object"
    assert "message" in params["properties"]
    assert params["properties"]["message"]["type"] == "string"


async def test_tool_execute_returns_tool_result():
    t = _EchoTool()
    ctx = ToolContext(project_root=Path("/tmp"), project_id=1, turn_id="t_1")
    result = await t.execute(_EchoArgs(message="hi"), ctx)
    assert isinstance(result, ToolResult)
    assert result.status == "ok"
    assert result.text == "hi"
    assert result.bytes_out == 2
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest plugin/tests/test_tool_base.py -v
```
Expected: `ModuleNotFoundError: No module named 'plugin.services.tools'`.

- [ ] **Step 3: Create `plugin/services/tools/base.py`**

```python
"""Tool Protocol + lightweight value types.

A tool is any object that conforms to the ``Tool`` Protocol:
- ``name``, ``description``, ``risk`` class attributes
- ``args_schema`` — a Pydantic BaseModel subclass describing the
  tool's input arguments
- async ``execute(args, ctx) -> ToolResult``

``ToolContext`` carries the minimal per-turn state a tool needs
(project_root for path resolution, project_id for logging, turn_id
for correlation). Phase 4b will extend it with approval callbacks and
audit-log hooks.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolContext:
    project_root: Path
    project_id: int
    turn_id: str


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

    async def execute(
        self, args: BaseModel, ctx: ToolContext
    ) -> ToolResult: ...


__all__ = ["Tool", "ToolContext", "ToolResult"]
```

- [ ] **Step 4: Create `plugin/services/tools/__init__.py`**

```python
"""Tool registry + Phase-4a convenience exports.

``default_registry()`` returns a ``ToolRegistry`` pre-populated with
the three Phase-4a tools (``read_file``, ``glob``, ``grep``). It is
built lazily in ``BaluCodePlugin.on_startup`` and passed into the WS
handler via the deps accessor.
"""
from __future__ import annotations

from plugin.services.tools.base import Tool, ToolContext, ToolResult


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


__all__ = ["Tool", "ToolContext", "ToolRegistry", "ToolResult"]
```

Task 8 will extend this with `default_registry()`; for now we leave it out.

- [ ] **Step 5: Run the tests**

```bash
pytest plugin/tests/test_tool_base.py -v
```
Expected: 6 passed.

- [ ] **Step 6: Full suite + ruff**

```bash
ruff check .
pytest
```
Expected: full suite grows by 6.

- [ ] **Step 7: Commit**

```bash
git add plugin/services/tools/__init__.py plugin/services/tools/base.py plugin/tests/test_tool_base.py
git commit -m "feat(plugin): add Tool Protocol + ToolRegistry (base + ollama_schemas)"
```

---

## Task 6: `read_file` tool

**Files:**
- Create: `plugin/services/tools/read_file.py`
- Create: `plugin/tests/test_tool_read_file.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_tool_read_file.py`:

```python
"""Tests for the read_file tool."""
from __future__ import annotations

from pathlib import Path

import pytest

from plugin.services.tools.base import ToolContext
from plugin.services.tools.read_file import ReadFileArgs, ReadFileTool


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(project_root=tmp_path, project_id=1, turn_id="t_1")


async def test_reads_utf8_file(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    t = ReadFileTool()
    result = await t.execute(ReadFileArgs(path="a.py"), _ctx(tmp_path))
    assert result.status == "ok"
    assert "def foo" in result.text
    assert result.bytes_out > 0


async def test_rejects_path_escape(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    t = ReadFileTool()
    result = await t.execute(
        ReadFileArgs(path="../escape.txt"), _ctx(tmp_path)
    )
    assert result.status == "error"
    assert "escape" in (result.error or "").lower() or "root" in (result.error or "").lower()


async def test_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    try:
        link = tmp_path / "link.txt"
        link.symlink_to(outside)
        t = ReadFileTool()
        result = await t.execute(ReadFileArgs(path="link.txt"), _ctx(tmp_path))
        assert result.status == "error"
    finally:
        if outside.exists():
            outside.unlink()


async def test_rejects_binary_file(tmp_path):
    (tmp_path / "img.bin").write_bytes(b"\x00\x01\x02\x03\x04")
    t = ReadFileTool()
    result = await t.execute(ReadFileArgs(path="img.bin"), _ctx(tmp_path))
    assert result.status == "error"
    assert "binary" in (result.error or "").lower()


async def test_returns_error_for_missing_file(tmp_path):
    t = ReadFileTool()
    result = await t.execute(ReadFileArgs(path="nope.py"), _ctx(tmp_path))
    assert result.status == "error"


async def test_truncates_at_max_bytes(tmp_path):
    (tmp_path / "big.py").write_text("x" * 10_000)
    t = ReadFileTool()
    result = await t.execute(
        ReadFileArgs(path="big.py", max_bytes=100), _ctx(tmp_path)
    )
    assert result.status == "ok"
    assert len(result.text.encode("utf-8", errors="replace")) <= 100
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest plugin/tests/test_tool_read_file.py -v
```
Expected: `ModuleNotFoundError: No module named 'plugin.services.tools.read_file'`.

- [ ] **Step 3: Implement `plugin/services/tools/read_file.py`**

```python
"""read_file tool — read a project-root-relative text file.

Path containment is verified inline here rather than in a shared helper:
Phase 4b extracts the check to ``plugin/services/paths.py`` when the
write-side tools land and the same logic is needed twice.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from plugin.services.tools.base import ToolContext, ToolResult


class ReadFileArgs(BaseModel):
    path: str = Field(..., min_length=1, description="Path relative to project root.")
    max_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1,
        le=10 * 1024 * 1024,
        description="Maximum bytes to read (default 2 MB, cap 10 MB).",
    )


def _contained(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


class ReadFileTool:
    name = "read_file"
    description = (
        "Read the contents of a text file relative to the project root. "
        "Returns up to 2 MB by default."
    )
    args_schema = ReadFileArgs
    risk = "read"

    async def execute(self, args: ReadFileArgs, ctx: ToolContext) -> ToolResult:
        candidate = ctx.project_root / args.path
        if not _contained(candidate, ctx.project_root):
            return ToolResult(
                status="error",
                text="",
                error=f"path '{args.path}' escapes project root",
            )
        resolved = candidate.resolve(strict=False)
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

- [ ] **Step 4: Run the tests**

```bash
pytest plugin/tests/test_tool_read_file.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Full suite + ruff**

```bash
ruff check .
pytest
```
Expected: full suite grows by 6.

- [ ] **Step 6: Commit**

```bash
git add plugin/services/tools/read_file.py plugin/tests/test_tool_read_file.py
git commit -m "feat(plugin): add read_file tool (path-containment + binary detection + 2 MB cap)"
```

---

## Task 7: `glob` tool

**Files:**
- Create: `plugin/services/tools/glob_tool.py`
- Create: `plugin/tests/test_tool_glob.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_tool_glob.py`:

```python
"""Tests for the glob tool."""
from __future__ import annotations

from pathlib import Path

from plugin.services.tools.base import ToolContext
from plugin.services.tools.glob_tool import GlobArgs, GlobTool


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(project_root=tmp_path, project_id=1, turn_id="t_1")


async def test_returns_matching_files(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    (tmp_path / "b.py").write_text("y\n")
    (tmp_path / "c.txt").write_text("z\n")
    t = GlobTool()
    result = await t.execute(GlobArgs(pattern="*.py"), _ctx(tmp_path))
    assert result.status == "ok"
    paths = set(result.text.splitlines())
    assert paths == {"a.py", "b.py"}


async def test_excludes_ignored_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "keep.py").write_text("x\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("x\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.py").write_text("x\n")
    t = GlobTool()
    result = await t.execute(GlobArgs(pattern="**/*.py"), _ctx(tmp_path))
    assert result.status == "ok"
    paths = set(result.text.splitlines())
    assert paths == {"src/keep.py"}


async def test_empty_match_returns_empty_text(tmp_path):
    t = GlobTool()
    result = await t.execute(GlobArgs(pattern="*.nonesuch"), _ctx(tmp_path))
    assert result.status == "ok"
    assert result.text == ""


async def test_caps_results_at_1000(tmp_path):
    for i in range(1050):
        (tmp_path / f"f_{i:04d}.py").write_text("x\n")
    t = GlobTool()
    result = await t.execute(GlobArgs(pattern="*.py"), _ctx(tmp_path))
    assert result.status == "ok"
    lines = result.text.splitlines()
    assert len(lines) == 1000
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest plugin/tests/test_tool_glob.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `plugin/services/tools/glob_tool.py`**

```python
"""glob tool — enumerate project files matching a POSIX-style glob.

Honors the shared IGNORE_DIRS list from ``plugin.services.repo_map``
so ``.venv``, ``node_modules``, ``__pycache__``, etc. are never
reported.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from plugin.services.repo_map import IGNORE_DIRS
from plugin.services.tools.base import ToolContext, ToolResult

_MAX_RESULTS = 1000


class GlobArgs(BaseModel):
    pattern: str = Field(
        ...,
        min_length=1,
        description="POSIX-style glob, relative to the project root.",
    )


class GlobTool:
    name = "glob"
    description = (
        "Enumerate files matching a POSIX-style glob pattern relative to "
        "the project root. Ignores .venv, node_modules, __pycache__, etc. "
        "Truncated at 1000 results."
    )
    args_schema = GlobArgs
    risk = "read"

    async def execute(self, args: GlobArgs, ctx: ToolContext) -> ToolResult:
        matches: list[str] = []
        for p in ctx.project_root.glob(args.pattern):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(ctx.project_root)
            except ValueError:
                continue
            if any(part in IGNORE_DIRS for part in rel.parts):
                continue
            matches.append(rel.as_posix())
            if len(matches) >= _MAX_RESULTS:
                break
        matches.sort()
        text = "\n".join(matches)
        return ToolResult(status="ok", text=text, bytes_out=len(text))


__all__ = ["GlobArgs", "GlobTool"]
```

- [ ] **Step 4: Run tests**

```bash
pytest plugin/tests/test_tool_glob.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Full suite + ruff**

```bash
ruff check .
pytest
```
Expected: full suite grows by 4.

- [ ] **Step 6: Commit**

```bash
git add plugin/services/tools/glob_tool.py plugin/tests/test_tool_glob.py
git commit -m "feat(plugin): add glob tool (IGNORE_DIRS filter + 1000-result cap)"
```

---

## Task 8: `grep` tool + `default_registry()`

**Files:**
- Create: `plugin/services/tools/grep_tool.py`
- Modify: `plugin/services/tools/__init__.py`
- Create: `plugin/tests/test_tool_grep.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_tool_grep.py`:

```python
"""Tests for the grep tool."""
from __future__ import annotations

from pathlib import Path

from plugin.services.tools.base import ToolContext
from plugin.services.tools.grep_tool import GrepArgs, GrepTool


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(project_root=tmp_path, project_id=1, turn_id="t_1")


async def test_finds_literal_match(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    return 42\n")
    (tmp_path / "b.py").write_text("def bar():\n    return 0\n")
    t = GrepTool()
    result = await t.execute(GrepArgs(pattern="foo"), _ctx(tmp_path))
    assert result.status == "ok"
    assert "a.py" in result.text
    assert "foo" in result.text
    assert "b.py" not in result.text


async def test_case_insensitive(tmp_path):
    (tmp_path / "a.py").write_text("DEF Foo():\n    pass\n")
    t = GrepTool()
    result = await t.execute(
        GrepArgs(pattern="foo", case_insensitive=True), _ctx(tmp_path)
    )
    assert result.status == "ok"
    assert "a.py" in result.text


async def test_honors_glob_filter(tmp_path):
    (tmp_path / "a.py").write_text("target\n")
    (tmp_path / "b.txt").write_text("target\n")
    t = GrepTool()
    result = await t.execute(
        GrepArgs(pattern="target", glob="*.py"), _ctx(tmp_path)
    )
    assert "a.py" in result.text
    assert "b.txt" not in result.text


async def test_excludes_ignored_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("target\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "leaked.py").write_text("target\n")
    t = GrepTool()
    result = await t.execute(GrepArgs(pattern="target"), _ctx(tmp_path))
    assert "src/a.py" in result.text
    assert ".venv" not in result.text


async def test_zero_matches_returns_empty_text(tmp_path):
    (tmp_path / "a.py").write_text("nothing interesting\n")
    t = GrepTool()
    result = await t.execute(GrepArgs(pattern="xyzzy"), _ctx(tmp_path))
    assert result.status == "ok"
    assert result.text == ""
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest plugin/tests/test_tool_grep.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `plugin/services/tools/grep_tool.py`**

```python
"""grep tool — regex search over project files.

Uses ripgrep (``rg``) as a subprocess when available; falls back to a
pure-Python ``re`` scan otherwise. Output format is always
``path:line:content`` (one match per line). Max 500 matches.
"""
from __future__ import annotations

import asyncio
import re
import shutil

from pydantic import BaseModel, Field

from plugin.services.repo_map import IGNORE_DIRS
from plugin.services.tools.base import ToolContext, ToolResult

_MAX_MATCHES = 500
_MAX_FILE_BYTES = 2 * 1024 * 1024


class GrepArgs(BaseModel):
    pattern: str = Field(..., min_length=1, description="Python-style regex.")
    glob: str | None = Field(
        default=None, description="Optional glob to restrict the search."
    )
    case_insensitive: bool = False


class GrepTool:
    name = "grep"
    description = (
        "Search file contents for a regex pattern. Uses ripgrep when "
        "available, else pure-Python. Honors IGNORE_DIRS. Max 500 matches."
    )
    args_schema = GrepArgs
    risk = "read"

    async def execute(self, args: GrepArgs, ctx: ToolContext) -> ToolResult:
        rg = shutil.which("rg")
        if rg is not None:
            lines = await self._run_rg(rg, args, ctx)
        else:
            lines = await asyncio.to_thread(self._run_python, args, ctx)
        text = "\n".join(lines)
        return ToolResult(status="ok", text=text, bytes_out=len(text))

    async def _run_rg(
        self, rg: str, args: GrepArgs, ctx: ToolContext
    ) -> list[str]:
        cmd = [
            rg,
            "--line-number",
            "--no-heading",
            "--color=never",
            "--max-count",
            str(_MAX_MATCHES),
        ]
        if args.case_insensitive:
            cmd.append("-i")
        if args.glob is not None:
            cmd.extend(["-g", args.glob])
        for d in sorted(IGNORE_DIRS):
            cmd.extend(["-g", f"!{d}/**"])
        cmd.extend(["-e", args.pattern, str(ctx.project_root)])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
        except OSError:
            return await asyncio.to_thread(self._run_python, args, ctx)
        lines: list[str] = []
        for raw in stdout.decode("utf-8", errors="replace").splitlines():
            if not raw:
                continue
            rel = self._strip_root(raw, ctx)
            lines.append(rel)
            if len(lines) >= _MAX_MATCHES:
                break
        return lines

    def _strip_root(self, line: str, ctx: ToolContext) -> str:
        prefix = str(ctx.project_root.resolve()) + "/"
        if line.startswith(prefix):
            return line[len(prefix):]
        return line

    def _run_python(self, args: GrepArgs, ctx: ToolContext) -> list[str]:
        flags = re.IGNORECASE if args.case_insensitive else 0
        regex = re.compile(args.pattern, flags)
        matches: list[str] = []
        if args.glob is not None:
            candidates = list(ctx.project_root.glob(args.glob))
        else:
            candidates = list(ctx.project_root.rglob("*"))
        for p in candidates:
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(ctx.project_root)
            except ValueError:
                continue
            if any(part in IGNORE_DIRS for part in rel.parts):
                continue
            try:
                with p.open("rb") as f:
                    data = f.read(_MAX_FILE_BYTES)
            except OSError:
                continue
            text = data.decode("utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{rel.as_posix()}:{i}:{line}")
                    if len(matches) >= _MAX_MATCHES:
                        return matches
        return matches


__all__ = ["GrepArgs", "GrepTool"]
```

- [ ] **Step 4: Extend `plugin/services/tools/__init__.py`** — add `default_registry()`

Append at the end of the file (after the current `__all__` — then move `__all__` to the very end):

```python
from plugin.services.tools.glob_tool import GlobTool
from plugin.services.tools.grep_tool import GrepTool
from plugin.services.tools.read_file import ReadFileTool


def default_registry() -> ToolRegistry:
    """Return a ToolRegistry pre-populated with the Phase-4a read tools."""
    reg = ToolRegistry()
    reg.register(ReadFileTool())
    reg.register(GlobTool())
    reg.register(GrepTool())
    return reg
```

Update `__all__` (at the top-level of the module) to include `"default_registry"` alphabetically:

```python
__all__ = [
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "default_registry",
]
```

- [ ] **Step 5: Run tests**

```bash
pytest plugin/tests/test_tool_grep.py -v
```
Expected: 5 passed.

- [ ] **Step 6: Full suite + ruff**

```bash
ruff check .
pytest
```
Expected: full suite grows by 5.

- [ ] **Step 7: Commit**

```bash
git add plugin/services/tools/grep_tool.py plugin/services/tools/__init__.py plugin/tests/test_tool_grep.py
git commit -m "feat(plugin): add grep tool + default_registry() helper"
```

---

## Task 9: `context_assembler.py`

**Files:**
- Create: `plugin/services/context_assembler.py`
- Create: `plugin/tests/test_context_assembler.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_context_assembler.py`:

```python
"""Tests for assemble_context."""
from __future__ import annotations

from plugin.services.context_assembler import AssembledContext, assemble_context
from plugin.services.rag_chunker import Chunk
from plugin.services.rag_index import SearchHit


def _hit(path: str, text: str, score: float) -> SearchHit:
    return SearchHit(
        chunk=Chunk(file_path=path, start_line=1, end_line=5, text=text),
        score=score,
    )


async def test_message_order_is_system_tool_use_repo_rag_history_user():
    ctx = await assemble_context(
        system_prompt="SYSPROMPT",
        tool_use_prompt="TOOLUSE",
        repo_map_text="=== foo.py ===",
        rag_hits=[_hit("foo.py", "hit text", 0.9)],
        history=[{"role": "assistant", "content": "earlier reply"}],
        user_message="current user ask",
        context_window=100_000,
        repo_map_budget=1024,
        rag_budget=1024,
    )
    roles_and_hints = [
        (m["role"], m["content"][:40]) for m in ctx.messages
    ]
    assert roles_and_hints[0] == ("system", "SYSPROMPT")
    assert roles_and_hints[1] == ("system", "TOOLUSE")
    assert "=== foo.py ===" in ctx.messages[2]["content"]
    assert "hit text" in ctx.messages[3]["content"]
    assert ctx.messages[4]["role"] == "assistant"
    assert ctx.messages[4]["content"] == "earlier reply"
    assert ctx.messages[5]["role"] == "user"
    assert ctx.messages[5]["content"] == "current user ask"


async def test_context_tokens_field_matches_messages_tokens():
    from plugin.services.tokenizer import count_messages_tokens

    ctx = await assemble_context(
        system_prompt="s",
        tool_use_prompt="t",
        repo_map_text="",
        rag_hits=[],
        history=[],
        user_message="u",
        context_window=100_000,
        repo_map_budget=1024,
        rag_budget=1024,
    )
    assert ctx.context_tokens == count_messages_tokens(ctx.messages)


async def test_system_and_tool_use_are_never_dropped():
    # A huge user message will overflow the window, but system/tool_use
    # must survive.
    ctx = await assemble_context(
        system_prompt="SYSPROMPT",
        tool_use_prompt="TOOLUSE",
        repo_map_text="x" * 200_000,
        rag_hits=[_hit("a", "y" * 200_000, 0.5)],
        history=[{"role": "user", "content": "old"}, {"role": "assistant", "content": "old reply"}],
        user_message="current",
        context_window=500,
        repo_map_budget=100_000,
        rag_budget=100_000,
    )
    # The system + tool_use prompts + user message must still appear.
    contents = [m["content"] for m in ctx.messages]
    assert any("SYSPROMPT" in c for c in contents)
    assert any("TOOLUSE" in c for c in contents)
    assert any(c == "current" for c in contents)


async def test_drops_oldest_history_turn_first():
    # Budget allows everything except one history turn.
    ctx = await assemble_context(
        system_prompt="s",
        tool_use_prompt="t",
        repo_map_text="",
        rag_hits=[],
        history=[
            {"role": "user", "content": "OLDEST" + "x" * 400},
            {"role": "assistant", "content": "MID"},
            {"role": "user", "content": "NEW"},
        ],
        user_message="current",
        context_window=60,
        repo_map_budget=1024,
        rag_budget=1024,
    )
    texts = " ".join(m["content"] for m in ctx.messages)
    assert "OLDEST" not in texts
    assert ctx.dropped_turns >= 1


async def test_drops_lowest_score_rag_chunks():
    ctx = await assemble_context(
        system_prompt="s",
        tool_use_prompt="t",
        repo_map_text="",
        rag_hits=[
            _hit("a.py", "A" + "x" * 400, 0.9),
            _hit("b.py", "B" + "x" * 400, 0.1),
            _hit("c.py", "C" + "x" * 400, 0.5),
        ],
        history=[],
        user_message="u",
        context_window=150,
        repo_map_budget=10_000,
        rag_budget=10_000,
    )
    # b.py was lowest-scoring; it should be dropped first.
    assert ctx.dropped_chunks >= 1


async def test_returns_AssembledContext():
    ctx = await assemble_context(
        system_prompt="s",
        tool_use_prompt="t",
        repo_map_text="",
        rag_hits=[],
        history=[],
        user_message="u",
        context_window=10_000,
        repo_map_budget=1024,
        rag_budget=1024,
    )
    assert isinstance(ctx, AssembledContext)
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest plugin/tests/test_context_assembler.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `plugin/services/context_assembler.py`**

```python
"""Build the OpenAI-style message array for one agent-loop turn.

Order: system prompt → tool-use prompt → repo-map block → RAG block →
session history → current user message. If the resulting total exceeds
``context_window``, drop in this order:
  (a) oldest history turns, one at a time,
  (b) lowest-score RAG chunks,
  (c) lowest-rank repo-map file blocks (block = chunk delimited by
      lines starting with ``=== ``).
System prompt, tool-use prompt, and the current user message are never
dropped.
"""
from __future__ import annotations

from dataclasses import dataclass

from plugin.services.rag_index import SearchHit
from plugin.services.tokenizer import count_messages_tokens, count_tokens


@dataclass(frozen=True)
class AssembledContext:
    messages: list[dict]
    context_tokens: int
    repo_map_tokens: int
    rag_tokens: int
    history_tokens: int
    truncated_files: list[str]
    dropped_turns: int
    dropped_chunks: int


def _format_rag_hits(hits: list[SearchHit]) -> str:
    blocks = [
        f"=== {h.chunk.file_path}:{h.chunk.start_line}-{h.chunk.end_line}\n{h.chunk.text}"
        for h in hits
    ]
    return "\n\n".join(blocks)


def _trim_rag(hits: list[SearchHit], budget_tokens: int) -> tuple[str, list[SearchHit]]:
    """Return (rendered_text, kept_hits). Drops lowest-score first."""
    sorted_hits = sorted(hits, key=lambda h: h.score, reverse=True)
    kept = list(sorted_hits)
    while kept:
        text = _format_rag_hits(kept)
        if count_tokens(text) <= budget_tokens:
            return text, kept
        kept.pop()  # drop lowest remaining
    return "", []


def _trim_repo_map(repo_map_text: str, budget_tokens: int) -> tuple[str, list[str]]:
    """Return (trimmed_text, truncated_file_paths). Drops trailing ``=== path`` blocks."""
    if count_tokens(repo_map_text) <= budget_tokens:
        return repo_map_text, []
    blocks: list[str] = []
    current: list[str] = []
    for line in repo_map_text.splitlines(keepends=True):
        if line.startswith("=== ") and current:
            blocks.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("".join(current))
    truncated: list[str] = []
    while blocks and count_tokens("".join(blocks)) > budget_tokens:
        dropped = blocks.pop()
        first_line = dropped.splitlines()[0] if dropped else ""
        if first_line.startswith("=== "):
            header = first_line[4:].split(" ", 1)[0]
            truncated.append(header)
    return "".join(blocks), truncated


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
    repo_map_trimmed, truncated_files = _trim_repo_map(repo_map_text, repo_map_budget)
    rag_text, kept_hits = _trim_rag(rag_hits, rag_budget)
    dropped_chunks = len(rag_hits) - len(kept_hits)

    def build(history_slice: list[dict]) -> list[dict]:
        msgs: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": tool_use_prompt},
        ]
        if repo_map_trimmed:
            msgs.append({"role": "system", "content": repo_map_trimmed})
        if rag_text:
            msgs.append({"role": "system", "content": rag_text})
        msgs.extend(history_slice)
        msgs.append({"role": "user", "content": user_message})
        return msgs

    history_slice = list(history)
    dropped_turns = 0
    messages = build(history_slice)

    while count_messages_tokens(messages) > context_window and history_slice:
        history_slice.pop(0)
        dropped_turns += 1
        messages = build(history_slice)

    while count_messages_tokens(messages) > context_window and kept_hits:
        kept_hits.pop()
        dropped_chunks += 1
        rag_text = _format_rag_hits(kept_hits)
        messages = build(history_slice)

    while count_messages_tokens(messages) > context_window and repo_map_trimmed:
        new_budget = max(0, count_tokens(repo_map_trimmed) - 500)
        repo_map_trimmed, more_truncated = _trim_repo_map(repo_map_trimmed, new_budget)
        truncated_files.extend(more_truncated)
        if not more_truncated and repo_map_trimmed:
            repo_map_trimmed = ""
        messages = build(history_slice)

    repo_tokens = count_tokens(repo_map_trimmed) if repo_map_trimmed else 0
    rag_tokens = count_tokens(rag_text) if rag_text else 0
    hist_tokens = count_messages_tokens(history_slice)

    return AssembledContext(
        messages=messages,
        context_tokens=count_messages_tokens(messages),
        repo_map_tokens=repo_tokens,
        rag_tokens=rag_tokens,
        history_tokens=hist_tokens,
        truncated_files=truncated_files,
        dropped_turns=dropped_turns,
        dropped_chunks=dropped_chunks,
    )


__all__ = ["AssembledContext", "assemble_context"]
```

- [ ] **Step 4: Run tests**

```bash
pytest plugin/tests/test_context_assembler.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Full suite + ruff**

```bash
ruff check .
pytest
```
Expected: full suite grows by 6.

- [ ] **Step 6: Commit**

```bash
git add plugin/services/context_assembler.py plugin/tests/test_context_assembler.py
git commit -m "feat(plugin): add context_assembler (budget-trimmed OpenAI message array)"
```

---

## Task 10: Prompts — `system.md` + `tool_use.md`

**Files:**
- Create: `plugin/prompts/system.md`
- Create: `plugin/prompts/tool_use.md`

This task creates the two prompt files that `agent_loop.py` reads at import time.

- [ ] **Step 1: Create `plugin/prompts/system.md`**

```markdown
# Balu Code — System Prompt

You are Balu Code, a self-hosted coding agent running on the user's own
machine via Ollama. You help the user understand, navigate, and modify
their codebase.

## Context you receive

Every turn you are given:
- A repository map showing top-level symbols from each Python file in
  the project.
- Semantically-retrieved chunks of code that match the user's question.
- The recent conversation history (if any).
- The user's latest message.

The repo map and retrieved chunks are summaries. They can mislead. When
you need ground truth about a file, read it.

## Priorities

1. **Read before you assert.** Do not claim what a file does without
   having read it, unless the behavior is trivially obvious from its
   name and signature.
2. **Surgical edits.** Prefer the smallest change that correctly
   addresses the user's ask. Do not rewrite working code for cosmetics.
3. **Stick to evidence.** Never fabricate code that is not in the
   retrieved context. If you need something you cannot see, use the
   available tools to find it.
4. **One clarifying question at most.** If the request is ambiguous,
   ask a single question. If it is clear enough to start, proceed.

## Style

- Match the user's language (German or English). If the user writes in
  German, reply in German.
- Be direct. No filler, no apologies, no preamble.
- When showing code, fence it in triple backticks with a language hint.
- When referencing file locations, use the `path:line` convention so
  the user can navigate directly.

## Response shape

- Start with your plan in one or two sentences.
- Make tool calls as needed, in the same turn.
- Explain the result briefly at the end.
```

- [ ] **Step 2: Create `plugin/prompts/tool_use.md`**

```markdown
# Tool use

In Phase 4a you have three tools. All three are read-only and
auto-approved — you do not need to ask permission before calling them.

## `read_file`

Read the contents of one file relative to the project root.

- `path` (required): project-root-relative path.
- `max_bytes` (optional, default 2 MB): cap on bytes read.
- Returns the file's text content.
- Errors: path outside project root; binary file; file not found.

## `glob`

Enumerate files matching a POSIX-style glob pattern.

- `pattern` (required): POSIX glob, relative to project root.
- Returns a newline-separated list of relative paths, up to 1000.
- Ignore directories (`.venv`, `node_modules`, `__pycache__`, etc.) are
  filtered out automatically.

## `grep`

Search file contents for a regex pattern.

- `pattern` (required): Python-style regex.
- `glob` (optional): restrict search to paths matching this glob.
- `case_insensitive` (optional, default false).
- Returns up to 500 `path:line:content` matches.
- Uses ripgrep when available, else pure-Python.

## Guidelines

- Use `glob` or `grep` to locate relevant files, then `read_file` to
  pull the full text of a specific region.
- Do not repeat the same tool call with the same arguments — check
  your prior tool results first.
- If a tool returns `status: "error"`, acknowledge the failure and
  either take a different approach or explain to the user why you
  cannot proceed. Do not retry blindly.
- Batch related `read_file` calls in a single turn when you know
  which files you need. Each tool call is a round-trip.
```

- [ ] **Step 3: Verify files exist and have content**

```bash
test -s plugin/prompts/system.md && test -s plugin/prompts/tool_use.md && echo ok
```
Expected: `ok`.

- [ ] **Step 4: Full suite + ruff**

```bash
ruff check .
pytest
```
Expected: full suite unchanged (no Python code added).

- [ ] **Step 5: Commit**

```bash
git add plugin/prompts/system.md plugin/prompts/tool_use.md
git commit -m "feat(plugin): add agent system + tool-use prompts"
```

---

## Task 11: `agent_loop.py` — `run_turn`

**Files:**
- Create: `plugin/services/agent_loop.py`
- Create: `plugin/tests/test_agent_loop.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_agent_loop.py`:

```python
"""Tests for run_turn (agent loop)."""
from __future__ import annotations

from dataclasses import replace

import pytest

from balu_code_shared.events import (
    Error,
    Event,
    ToolCall,
    ToolResult,
    TurnEnd,
)

from plugin.config import BaluCodePluginConfig
from plugin.services.agent_loop import TurnDeps, run_turn
from plugin.services.project_store import Project, ProjectStore
from plugin.services.repo_map import RepoMap
from plugin.services.tools import default_registry


class _FakeOllama:
    def __init__(self, scripted: list[list[dict]]) -> None:
        self._scripted = list(scripted)

    async def chat_stream(self, model, messages, tools=None, options=None):
        frames = self._scripted.pop(0)
        for f in frames:
            yield f

    async def close(self) -> None:
        pass

    async def list_models(self):
        return []

    async def embed(self, model, texts):
        return [[0.0] * 768 for _ in texts]


class _FakeRag:
    async def search(self, query, top_k=8, *, keyword_boost=0.15):
        return []


@pytest.fixture
def tmp_project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def foo(): pass\n")
    return root


@pytest.fixture
def deps_factory(tmp_project, tmp_path):
    def make(scripted_frames: list[list[dict]]) -> TurnDeps:
        store = ProjectStore(tmp_path / "store.db")
        p = store.create_project(
            name="proj", root_path=str(tmp_project), config_yaml=None
        )
        project = Project(
            id=p.id, name=p.name, root_path=p.root_path, config_yaml=p.config_yaml,
            created_at=p.created_at, updated_at=p.updated_at,
        )
        repo_map = RepoMap(tmp_project, store, p.id)
        return TurnDeps(
            ollama=_FakeOllama(scripted_frames),
            tool_registry=default_registry(),
            project=project,
            repo_map=repo_map,
            rag=_FakeRag(),
            config=BaluCodePluginConfig(),
            system_prompt="sys",
            tool_use_prompt="tool",
        )
    return make


async def test_simple_turn_done_without_tool_calls(deps_factory):
    events: list[Event] = []

    async def emit(e):
        events.append(e)

    deps = deps_factory(
        [[
            {"message": {"content": "Hello", "tool_calls": None}, "done": False},
            {"message": {"content": " world", "tool_calls": None}, "done": True},
        ]]
    )
    history: list[dict] = []
    await run_turn("hi", history, deps, emit)

    types = [e.type for e in events]
    assert types[0] == "turn_start"
    assert "token" in types
    assert types[-1] == "turn_end"
    end = next(e for e in events if isinstance(e, TurnEnd))
    assert end.stop_reason == "done"


async def test_tool_call_dispatches_read_file(deps_factory):
    events: list[Event] = []

    async def emit(e):
        events.append(e)

    deps = deps_factory(
        [
            [
                {
                    "message": {
                        "content": "reading",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "read_file",
                                    "arguments": {"path": "a.py"},
                                }
                            }
                        ],
                    },
                    "done": True,
                }
            ],
            [
                {"message": {"content": "done", "tool_calls": None}, "done": True},
            ],
        ]
    )
    history: list[dict] = []
    await run_turn("what is in a.py?", history, deps, emit)

    tool_calls = [e for e in events if isinstance(e, ToolCall)]
    tool_results = [e for e in events if isinstance(e, ToolResult)]
    assert len(tool_calls) == 1
    assert tool_calls[0].tool == "read_file"
    assert tool_calls[0].auto_approved is True
    assert len(tool_results) == 1
    assert tool_results[0].status == "ok"
    assert tool_results[0].tool_call_id == tool_calls[0].tool_call_id


async def test_iteration_cap_yields_max_iter_stop_reason(deps_factory):
    frames_per_iter = [
        {
            "message": {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "glob", "arguments": {"pattern": "*.py"}}}
                ],
            },
            "done": True,
        }
    ]
    deps = deps_factory([frames_per_iter for _ in range(13)])
    deps.config.max_iterations = 2
    events: list[Event] = []

    async def emit(e):
        events.append(e)

    history: list[dict] = []
    await run_turn("loop forever", history, deps, emit)
    end = next(e for e in events if isinstance(e, TurnEnd))
    assert end.stop_reason == "max_iter"


async def test_ollama_error_surfaces_as_error_event(deps_factory):
    from plugin.services.ollama_client import OllamaUnreachable

    events: list[Event] = []

    async def emit(e):
        events.append(e)

    deps_fresh = deps_factory([[]])

    class _BrokenOllama:
        async def chat_stream(self, *a, **kw):
            raise OllamaUnreachable("down")
            yield  # noqa — mark as async gen

        async def close(self): pass

    deps = replace(deps_fresh, ollama=_BrokenOllama())
    history: list[dict] = []
    await run_turn("hi", history, deps, emit)
    errors = [e for e in events if isinstance(e, Error)]
    assert len(errors) == 1
    assert errors[0].code == "ollama_unreachable"
    end = next(e for e in events if isinstance(e, TurnEnd))
    assert end.stop_reason == "error"


async def test_unknown_tool_name_emits_error_tool_result(deps_factory):
    events: list[Event] = []

    async def emit(e):
        events.append(e)

    deps = deps_factory(
        [
            [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "no_such_tool", "arguments": {}}}
                        ],
                    },
                    "done": True,
                }
            ],
            [
                {"message": {"content": "ok", "tool_calls": None}, "done": True},
            ],
        ]
    )
    history: list[dict] = []
    await run_turn("use a tool", history, deps, emit)
    tool_results = [e for e in events if isinstance(e, ToolResult)]
    assert len(tool_results) == 1
    assert tool_results[0].status == "error"
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest plugin/tests/test_agent_loop.py -v
```
Expected: `ModuleNotFoundError: No module named 'plugin.services.agent_loop'`.

- [ ] **Step 3: Implement `plugin/services/agent_loop.py`**

```python
"""Main agent-loop runtime.

One ``run_turn`` call drives a single user-message turn end-to-end:
assembles context, streams from Ollama, dispatches tool calls,
accumulates history, emits WS events via the provided callback. The
function never raises; all failures become an ``Error`` event plus
``TurnEnd(stop_reason="error")``.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from balu_code_shared.events import (
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
from plugin.services.tokenizer import count_tokens
from plugin.services.tools import ToolRegistry
from plugin.services.tools.base import ToolContext

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system.md"
_TOOL_USE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "tool_use.md"

_SYSTEM_PROMPT = _SYSTEM_PROMPT_PATH.read_text()
_TOOL_USE_PROMPT = _TOOL_USE_PROMPT_PATH.read_text()


@dataclass
class TurnDeps:
    """Dependencies a turn needs. Mutable only for the config field in tests."""

    ollama: OllamaClient
    tool_registry: ToolRegistry
    project: Project
    repo_map: RepoMap
    rag: RagIndex
    config: BaluCodePluginConfig
    system_prompt: str = _SYSTEM_PROMPT
    tool_use_prompt: str = _TOOL_USE_PROMPT


Emitter = Callable[[Event], Awaitable[None]]


def _new_turn_id() -> str:
    return f"t_{uuid.uuid4().hex[:12]}"


def _new_tool_call_id(iteration: int) -> str:
    return f"tc_{iteration}_{uuid.uuid4().hex[:6]}"


async def run_turn(
    user_message: str,
    history: list[dict],
    deps: TurnDeps,
    emit: Emitter,
) -> None:
    """Drive one turn. Appends to ``history`` in place. Never raises."""
    turn_id = _new_turn_id()
    try:
        repo_map_text = await _resolve_repo_map(deps)
    except Exception as exc:
        await emit(Error(code="repo_map_failed", message=str(exc)))
        await emit(TurnEnd(turn_id=turn_id, total_tokens=0, iterations=0, stop_reason="error"))
        return

    try:
        rag_hits = await deps.rag.search(
            user_message, top_k=deps.config.rag_top_k
        )
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
    except Exception as exc:
        history[:] = history_snapshot
        await emit(Error(code="context_assembly_failed", message=str(exc)))
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
    for iteration in range(deps.config.max_iterations):
        iterations += 1
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
        except OllamaUnreachable as exc:
            history[:] = history_snapshot
            await emit(Error(code="ollama_unreachable", message=str(exc)))
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="error",
                )
            )
            return
        except OllamaTimeoutError as exc:
            history[:] = history_snapshot
            await emit(Error(code="ollama_timeout", message=str(exc)))
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="error",
                )
            )
            return
        except OllamaRateLimited as exc:
            history[:] = history_snapshot
            await emit(Error(code="ollama_rate_limited", message=str(exc)))
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="error",
                )
            )
            return
        except Exception as exc:
            history[:] = history_snapshot
            await emit(Error(code="internal", message=f"{type(exc).__name__}: {exc}"))
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="error",
                )
            )
            return

        total_tokens += count_tokens(buffered_content)
        if total_tokens > deps.config.max_total_tokens_per_turn:
            history.append({"role": "assistant", "content": buffered_content})
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="max_iter",
                )
            )
            return

        if not tool_calls_from_stream:
            history.append({"role": "assistant", "content": buffered_content})
            await emit(
                TurnEnd(
                    turn_id=turn_id,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="done",
                )
            )
            return

        assistant_msg: dict = {"role": "assistant", "content": buffered_content}
        assistant_msg["tool_calls"] = tool_calls_from_stream
        history.append(assistant_msg)
        messages.append(assistant_msg)

        tool_ctx = ToolContext(
            project_root=Path(deps.project.root_path),
            project_id=deps.project.id,
            turn_id=turn_id,
        )
        for call in tool_calls_from_stream:
            function = call.get("function") or {}
            name = function.get("name") or ""
            raw_args = function.get("arguments")
            try:
                args_dict = (
                    raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
                )
            except (json.JSONDecodeError, ValueError):
                args_dict = {}
            tc_id = _new_tool_call_id(iterations)

            await emit(
                ToolCall(
                    tool_call_id=tc_id, tool=name, args=args_dict, auto_approved=True
                )
            )
            try:
                tool = deps.tool_registry.get(name)
            except KeyError:
                msg = f"unknown tool '{name}'"
                await emit(
                    ToolResult(
                        tool_call_id=tc_id, status="error", bytes_out=0, error=msg
                    )
                )
                tool_msg = {"role": "tool", "name": name, "content": f"error: {msg}"}
                history.append(tool_msg)
                messages.append(tool_msg)
                continue

            try:
                parsed = tool.args_schema.model_validate(args_dict)
            except ValidationError as exc:
                msg = f"invalid args: {exc}"
                await emit(
                    ToolResult(
                        tool_call_id=tc_id, status="error", bytes_out=0, error=msg
                    )
                )
                tool_msg = {"role": "tool", "name": name, "content": f"error: {msg}"}
                history.append(tool_msg)
                messages.append(tool_msg)
                continue

            try:
                result = await tool.execute(parsed, tool_ctx)
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                await emit(
                    ToolResult(
                        tool_call_id=tc_id, status="error", bytes_out=0, error=msg
                    )
                )
                tool_msg = {"role": "tool", "name": name, "content": f"error: {msg}"}
                history.append(tool_msg)
                messages.append(tool_msg)
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

    await emit(
        TurnEnd(
            turn_id=turn_id,
            total_tokens=total_tokens,
            iterations=iterations,
            stop_reason="max_iter",
        )
    )


async def _resolve_repo_map(deps: TurnDeps) -> str:
    """Walk the project + render a repo_map under the configured budget."""
    files = await asyncio.to_thread(deps.repo_map.walk_and_cache)
    rendered = deps.repo_map.render(files, budget_tokens=deps.config.repo_map_budget)
    return rendered.text


__all__ = ["TurnDeps", "run_turn"]
```

- [ ] **Step 4: Run agent_loop tests**

```bash
pytest plugin/tests/test_agent_loop.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Full suite + ruff**

```bash
ruff check .
pytest
```
Expected: full suite grows by 5.

- [ ] **Step 6: Commit**

```bash
git add plugin/services/agent_loop.py plugin/tests/test_agent_loop.py
git commit -m "feat(plugin): add run_turn (agent loop) with tool dispatch + error boundaries"
```

---

## Task 12: Lifecycle wiring — `deps.py` + `BaluCodePlugin`

**Files:**
- Modify: `plugin/deps.py`
- Modify: `plugin/__init__.py`
- Modify: `plugin/tests/test_plugin_lifecycle.py`

- [ ] **Step 1: Append failing tests to `plugin/tests/test_plugin_lifecycle.py`**

Add at the end:

```python
async def test_startup_registers_tool_registry_and_config(tmp_path, monkeypatch):
    from plugin.config import BaluCodePluginConfig
    from plugin.deps import (
        clear_singletons,
        get_plugin_config,
        get_tool_registry,
    )
    from plugin.services.tools import ToolRegistry

    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    clear_singletons()
    p = BaluCodePlugin()
    await p.on_startup()
    try:
        reg = get_tool_registry()
        cfg = get_plugin_config()
        assert isinstance(reg, ToolRegistry)
        assert reg.names() == ["glob", "grep", "read_file"]
        assert isinstance(cfg, BaluCodePluginConfig)
    finally:
        await p.on_shutdown()


async def test_shutdown_clears_tool_registry_and_config(tmp_path, monkeypatch):
    from plugin.deps import (
        clear_singletons,
        get_plugin_config,
        get_tool_registry,
    )

    monkeypatch.setenv("BALU_CODE_DATA_DIR", str(tmp_path))
    clear_singletons()
    p = BaluCodePlugin()
    await p.on_startup()
    await p.on_shutdown()
    with pytest.raises(RuntimeError):
        get_tool_registry()
    with pytest.raises(RuntimeError):
        get_plugin_config()
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest plugin/tests/test_plugin_lifecycle.py -v -k "tool_registry or plugin_config"
```
Expected: 2 failures.

- [ ] **Step 3: Extend `plugin/deps.py`**

Replace the body with:

```python
"""Module-level singletons for the balu_code plugin.

``BaluCodePlugin.on_startup`` constructs six singletons and registers
them here via ``set_singletons``. Route handlers access them via the
``get_*`` accessors; tests override via ``app.dependency_overrides``.
"""
from __future__ import annotations

from plugin.config import BaluCodePluginConfig
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


def set_singletons(
    store: ProjectStore,
    ollama: OllamaClient,
    rag_registry: RagRegistry,
    index_job_tracker: IndexJobTracker,
    tool_registry: ToolRegistry,
    plugin_config: BaluCodePluginConfig,
) -> None:
    global _store, _ollama, _rag_registry, _index_job_tracker, _tool_registry, _plugin_config
    _store = store
    _ollama = ollama
    _rag_registry = rag_registry
    _index_job_tracker = index_job_tracker
    _tool_registry = tool_registry
    _plugin_config = plugin_config


def clear_singletons() -> None:
    global _store, _ollama, _rag_registry, _index_job_tracker, _tool_registry, _plugin_config
    _store = None
    _ollama = None
    _rag_registry = None
    _index_job_tracker = None
    _tool_registry = None
    _plugin_config = None


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


__all__ = [
    "clear_singletons",
    "get_index_job_tracker",
    "get_ollama_client",
    "get_plugin_config",
    "get_project_store",
    "get_rag_registry",
    "get_tool_registry",
    "set_singletons",
]
```

- [ ] **Step 4: Extend `plugin/__init__.py`**

Replace the full file with:

```python
"""Balu Code BaluHost plugin.

Loaded at BaluHost startup by PluginManager. Exposes a FastAPI router
at /api/plugins/balu_code/ — see ``plugin/routes.py``. Owns six
singletons: ProjectStore, OllamaClient, RagRegistry, IndexJobTracker,
ToolRegistry, BaluCodePluginConfig.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.plugins.base import PluginBase, PluginMetadata
from fastapi import APIRouter

from plugin.config import BaluCodePluginConfig
from plugin.data_dir import resolve_data_dir
from plugin.deps import clear_singletons, set_singletons
from plugin.routes import build_router
from plugin.services.index_jobs import IndexJobTracker
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore
from plugin.services.rag_registry import RagRegistry
from plugin.services.tools import ToolRegistry, default_registry

_MANIFEST_PATH = Path(__file__).parent / "plugin.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())


class BaluCodePlugin(PluginBase):
    """Main plugin class. Metadata read from plugin.json at import time."""

    def __init__(self) -> None:
        self._config = BaluCodePluginConfig()
        self._store: ProjectStore | None = None
        self._ollama: OllamaClient | None = None
        self._rag_registry: RagRegistry | None = None
        self._index_job_tracker: IndexJobTracker | None = None
        self._tool_registry: ToolRegistry | None = None

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
        return build_router()

    def get_config_schema(self) -> type:
        return BaluCodePluginConfig

    def get_default_config(self) -> dict:
        return BaluCodePluginConfig().model_dump()

    async def on_startup(self) -> None:
        data_dir = resolve_data_dir()
        store = ProjectStore(data_dir / "store.db")
        try:
            ollama = OllamaClient(base_url=self._config.ollama_base_url)
        except BaseException:
            store.close()
            raise
        rag_registry = RagRegistry(
            data_dir=data_dir,
            embed_model=self._config.embed_model,
            ollama=ollama,
        )
        index_job_tracker = IndexJobTracker()
        tool_registry = default_registry()
        self._store = store
        self._ollama = ollama
        self._rag_registry = rag_registry
        self._index_job_tracker = index_job_tracker
        self._tool_registry = tool_registry
        set_singletons(
            store,
            ollama,
            rag_registry,
            index_job_tracker,
            tool_registry,
            self._config,
        )

    async def on_shutdown(self) -> None:
        if (
            self._store is None
            and self._ollama is None
            and self._rag_registry is None
            and self._index_job_tracker is None
            and self._tool_registry is None
        ):
            return
        if self._rag_registry is not None:
            await self._rag_registry.close_all()
        if self._ollama is not None:
            await self._ollama.close()
        if self._store is not None:
            self._store.close()
        clear_singletons()
        self._store = None
        self._ollama = None
        self._rag_registry = None
        self._index_job_tracker = None
        self._tool_registry = None


__all__ = ["BaluCodePlugin"]
```

- [ ] **Step 5: Run tests**

```bash
pytest plugin/tests/test_plugin_lifecycle.py -v
```
Expected: 9 passed (7 existing + 2 new).

- [ ] **Step 6: Full suite + ruff**

```bash
ruff check .
pytest
```
Expected: full suite grows by 2.

- [ ] **Step 7: Commit**

```bash
git add plugin/deps.py plugin/__init__.py plugin/tests/test_plugin_lifecycle.py
git commit -m "feat(plugin): wire ToolRegistry + BaluCodePluginConfig into lifecycle + deps"
```

---

## Task 13: WS `/chat` route

**Files:**
- Modify: `plugin/routes.py`
- Create: `plugin/tests/test_routes_chat.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_routes_chat.py`:

```python
"""Tests for the WebSocket /chat endpoint."""
from __future__ import annotations

import pytest
from app.api.deps import get_current_user
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin import BaluCodePlugin
from plugin.config import BaluCodePluginConfig
from plugin.deps import (
    get_index_job_tracker,
    get_ollama_client,
    get_plugin_config,
    get_project_store,
    get_rag_registry,
    get_tool_registry,
)
from plugin.services.index_jobs import IndexJobTracker
from plugin.services.project_store import ProjectStore
from plugin.services.tools import default_registry


class _FakeOllama:
    def __init__(self, scripted: list[list[dict]]) -> None:
        self._scripted = list(scripted)

    async def chat_stream(self, *a, **kw):
        frames = self._scripted.pop(0)
        for f in frames:
            yield f

    async def list_models(self):
        return []

    async def embed(self, model, texts):
        return [[0.0] * 768 for _ in texts]

    async def close(self):
        pass


class _FakeRagRegistry:
    async def get(self, project_id):
        class _Idx:
            async def search(self, query, top_k=8, *, keyword_boost=0.15):
                return []
        return _Idx()

    async def close_all(self):
        pass


@pytest.fixture
def store(tmp_path) -> ProjectStore:
    s = ProjectStore(tmp_path / "store.db")
    yield s
    s.close()


def _make_project(store: ProjectStore, root: str) -> int:
    return store.create_project(name="chat-route", root_path=root, config_yaml=None).id


def _client(store, ollama, rag_registry, tool_registry, config) -> TestClient:
    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_ollama_client] = lambda: ollama
    app.dependency_overrides[get_rag_registry] = lambda: rag_registry
    app.dependency_overrides[get_index_job_tracker] = lambda: IndexJobTracker()
    app.dependency_overrides[get_tool_registry] = lambda: tool_registry
    app.dependency_overrides[get_plugin_config] = lambda: config
    return TestClient(app)


def test_chat_happy_path(tmp_path, store):
    (tmp_path / "a.py").write_text("def foo(): pass\n")
    pid = _make_project(store, str(tmp_path))
    ollama = _FakeOllama(
        [[
            {"message": {"content": "Hello", "tool_calls": None}, "done": False},
            {"message": {"content": ".", "tool_calls": None}, "done": True},
        ]]
    )
    c = _client(store, ollama, _FakeRagRegistry(), default_registry(), BaluCodePluginConfig())
    with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
        ws.send_json({"type": "user_message", "content": "hi"})
        events = []
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] == "turn_end":
                break
    types = [e["type"] for e in events]
    assert types[0] == "turn_start"
    assert "token" in types
    assert types[-1] == "turn_end"


def test_chat_404_for_unknown_project(tmp_path, store):
    ollama = _FakeOllama([])
    c = _client(store, ollama, _FakeRagRegistry(), default_registry(), BaluCodePluginConfig())
    with pytest.raises(Exception):
        with c.websocket_connect("/api/plugins/balu_code/chat?project_id=9999"):
            pass


def test_chat_401_when_auth_fails(tmp_path, store):
    from fastapi import HTTPException, status as _status

    async def _denied():
        raise HTTPException(status_code=_status.HTTP_401_UNAUTHORIZED, detail="no")

    (tmp_path / "a.py").write_text("x\n")
    pid = _make_project(store, str(tmp_path))
    ollama = _FakeOllama([])
    app = FastAPI()
    plugin = BaluCodePlugin()
    app.include_router(plugin.get_router(), prefix="/api/plugins/balu_code")
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_ollama_client] = lambda: ollama
    app.dependency_overrides[get_rag_registry] = lambda: _FakeRagRegistry()
    app.dependency_overrides[get_index_job_tracker] = lambda: IndexJobTracker()
    app.dependency_overrides[get_tool_registry] = lambda: default_registry()
    app.dependency_overrides[get_plugin_config] = lambda: BaluCodePluginConfig()
    app.dependency_overrides[get_current_user] = _denied
    c = TestClient(app)
    with pytest.raises(Exception):
        with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}"):
            pass


def test_chat_multi_turn_preserves_history(tmp_path, store):
    (tmp_path / "a.py").write_text("def foo(): pass\n")
    pid = _make_project(store, str(tmp_path))
    ollama = _FakeOllama(
        [
            [
                {"message": {"content": "one", "tool_calls": None}, "done": True},
            ],
            [
                {"message": {"content": "two", "tool_calls": None}, "done": True},
            ],
        ]
    )
    c = _client(store, ollama, _FakeRagRegistry(), default_registry(), BaluCodePluginConfig())
    with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
        ws.send_json({"type": "user_message", "content": "first"})
        while True:
            ev = ws.receive_json()
            if ev["type"] == "turn_end":
                break
        ws.send_json({"type": "user_message", "content": "second"})
        turn2_events = []
        while True:
            ev = ws.receive_json()
            turn2_events.append(ev)
            if ev["type"] == "turn_end":
                break
    end2 = next(e for e in turn2_events if e["type"] == "turn_end")
    assert end2["stop_reason"] in ("done", "max_iter")


def test_chat_unsupported_frame_yields_error_and_stays_open(tmp_path, store):
    (tmp_path / "a.py").write_text("x\n")
    pid = _make_project(store, str(tmp_path))
    ollama = _FakeOllama([])
    c = _client(store, ollama, _FakeRagRegistry(), default_registry(), BaluCodePluginConfig())
    with c.websocket_connect(f"/api/plugins/balu_code/chat?project_id={pid}") as ws:
        ws.send_json({"type": "approval", "tool_call_id": "tc_x", "approved": True})
        ev = ws.receive_json()
        assert ev["type"] == "error"
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest plugin/tests/test_routes_chat.py -v
```
Expected: 5 failures (route doesn't exist).

- [ ] **Step 3: Extend `plugin/routes.py`**

Add new top-level imports (alphabetical):

```python
from balu_code_shared.events import Error, UserMessage, parse_frame
from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from plugin.config import BaluCodePluginConfig
from plugin.deps import (
    get_plugin_config,
    get_tool_registry,
)
from plugin.services.agent_loop import TurnDeps, run_turn
from plugin.services.rag_registry import RagRegistry
from plugin.services.repo_map import RepoMap
from plugin.services.tools import ToolRegistry
```

If any of these are already imported via earlier tasks, dedupe — ruff will flag duplicates.

Inside `build_router`, before the final `return router`, append:

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
        try:
            project = await asyncio.to_thread(store.get_project, project_id)
        except ProjectNotFoundError:
            await websocket.close(code=1008, reason="project not found")
            return

        try:
            rag = await rag_registry.get(project.id)
        except Exception as exc:
            await websocket.close(code=1011, reason=f"rag init failed: {exc}")
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
        )
        history: list[dict] = []

        async def _emit(event) -> None:
            await websocket.send_json(event.model_dump())

        try:
            while True:
                raw = await websocket.receive_json()
                try:
                    frame = parse_frame(raw)
                except ValidationError as exc:
                    await _emit(
                        Error(code="bad_frame", message=str(exc)[:200])
                    )
                    continue
                if isinstance(frame, UserMessage):
                    await run_turn(frame.content, history, deps, _emit)
                else:
                    await _emit(
                        Error(
                            code="unsupported_frame",
                            message=f"frame type '{frame.type}' is not supported in 4a",
                        )
                    )
        except WebSocketDisconnect:
            return
```

- [ ] **Step 4: Run the chat tests**

```bash
pytest plugin/tests/test_routes_chat.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Full suite + ruff**

```bash
ruff check .
ruff format --check .
pytest
```
Expected: full suite grows by 5.

- [ ] **Step 6: Commit**

```bash
git add plugin/routes.py plugin/tests/test_routes_chat.py
git commit -m "feat(plugin): add WS /chat route driving run_turn with connection-scoped history"
```

---

## Task 14: Phase 4a verification + push

**Files:**
- Create: `docs/phase-4a-verification.md`

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
- pytest: record actual count (≥ previous + ~32 new).
- `dist/` has `balu_code-0.1.0.bhplugin`, `.sha256`, `balu_code_cli-0.1.0-py3-none-any.whl`.

- [ ] **Step 2: Verify the `.bhplugin` includes Phase-4a modules + prompts**

```bash
python -c "
import zipfile
with zipfile.ZipFile('dist/balu_code-0.1.0.bhplugin') as zf:
    names = sorted(zf.namelist())
want = {
    'services/tokenizer.py',
    'services/context_assembler.py',
    'services/agent_loop.py',
    'services/tools/__init__.py',
    'services/tools/base.py',
    'services/tools/read_file.py',
    'services/tools/glob_tool.py',
    'services/tools/grep_tool.py',
    'prompts/system.md',
    'prompts/tool_use.md',
}
missing = want - set(names)
assert not missing, f'missing: {missing}'
print('ok', len(names), 'files')
"
```

Expected: `ok <N> files`.

- [ ] **Step 3: Create `docs/phase-4a-verification.md`**

Fill in actual values from the previous steps.

```markdown
# Phase 4a verification — 2026-04-19

## Environment (local dev)

- Commit: `<git rev-parse --short HEAD>`
- Python: 3.13.5 (CI matrix covers 3.11 & 3.12)

## Automated checks

- [x] `ruff check .` — clean
- [x] `ruff format --check .` — clean
- [x] `pytest -v` — `<N>` tests passing
- [x] `.bhplugin` includes all Phase-4a service modules + both prompt files
- [x] `python -m scripts.build_wheel` still produces the CLI wheel
- [ ] GitHub Actions: CI green on `main` (fill in after push)

## Manual checks against dev BaluHost

- [ ] Re-sideload the new `.bhplugin`.
- [ ] BaluHost venv installs `tiktoken`.
- [ ] Restart the BaluHost backend.
- [ ] Connect a WebSocket to `/api/plugins/balu_code/chat?project_id=<id>`,
      send a `user_message`, observe `turn_start` → tokens → `turn_end`.
- [ ] Ask a question that requires `read_file` (e.g. "What does foo.py do?");
      confirm `tool_call` + `tool_result` frames with `auto_approved: true`.

## Plan deviations

(List any follow-up commits after `5750e44` — use `git log --oneline 5750e44..HEAD` to enumerate.)

## Known issues carried into Phase 4b

- No write-side tools yet (`write_file`, `apply_patch`, `run_bash`, `web_fetch`).
- No `approval_request` / `approval` / `cancel` frames — cannot interrupt a turn.
- Path-containment is inline in `read_file.py`; extract to `plugin/services/paths.py` with 4b.
- Audit log not wired.
- Tokenizer is cl100k_base — ~15% error against qwen's real tokenizer. Acceptable for budgeting.
```

- [ ] **Step 4: Commit + push**

```bash
git add docs/phase-4a-verification.md
git commit -m "docs: add Phase 4a verification checklist"
git push
```

- [ ] **Step 5: Verify CI**

```bash
sleep 40
gh run list --limit 2
```

Expected: new run `completed success`. If `in_progress`, poll with `sleep 20 && gh run list --limit 2` up to ~3 min total. Once green, update the verification doc with the run URL and push a follow-up commit.

---

## Phase 4a Definition of Done

- All 14 tasks committed and pushed to `main`.
- CI green on `main` (both 3.11 and 3.12 matrix jobs).
- Full suite grows by ~32 tests, all green locally.
- `.bhplugin` archive contains all Phase-4a service files + both prompt markdown files.
- `WS /chat` happy path: send `user_message`, receive `turn_start` + tokens + `turn_end(stop_reason="done")`. Tool dispatch path: model's scripted `tool_calls` triggers `tool_call` + `tool_result` frames.

## What comes next (not this plan)

- **Phase 4b — write-side tools + approval gate + audit log + cancel.**
- **Phase 5 — CLI (Textual TUI, `.balucode.yaml`, session-resume priming frame).**
- **Phase 6 — UI bundle + docs + release.**
