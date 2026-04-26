# Balu Code Phase 5b — Session Storage + Config Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automatic client-side session persistence (JSONL) to the chat REPL and two new top-level command groups: `session list/resume/delete` and `config get/set`.

**Architecture:** A new `cli/src/balu_code_cli/session/` module owns all session I/O (`SessionWriter` appends WS events, `SessionReader` reconstructs messages). The `chat` command auto-creates a `SessionWriter` on every run (dependency injection via an optional parameter). `session resume` replays prior conversation visually then starts a fresh REPL. `config get/set` reads and writes `AppConfig` fields in `~/.config/balu-code/config.yaml`.

**Tech Stack:** Python 3.11+, Pydantic v2 (events are `BaseModel` subclasses with `model_dump()`), pyyaml, Typer, Rich, pytest + pytest-asyncio.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `cli/src/balu_code_cli/session/__init__.py` | Create | Package marker |
| `cli/src/balu_code_cli/session/writer.py` | Create | `SessionWriter` — append WS events as JSONL |
| `cli/src/balu_code_cli/session/reader.py` | Create | `SessionReader` — reconstruct messages + metadata |
| `cli/src/balu_code_cli/config/paths.py` | Modify | Add `sessions_dir(server_url, project_id)` |
| `cli/src/balu_code_cli/commands/chat.py` | Modify | Add `session_writer` + `initial_messages` DI to `run_chat` |
| `cli/src/balu_code_cli/commands/session.py` | Create | `session list / resume / delete` |
| `cli/src/balu_code_cli/commands/config.py` | Create | `config get / set` |
| `cli/src/balu_code_cli/__main__.py` | Modify | Register `session_app` and `config_app` |
| `cli/tests/test_session_writer.py` | Create | Unit tests for `SessionWriter` |
| `cli/tests/test_session_reader.py` | Create | Unit tests for `SessionReader` |
| `cli/tests/test_cmd_session.py` | Create | Command tests for `session` subcommands |
| `cli/tests/test_cmd_config.py` | Create | Command tests for `config` subcommands |
| `cli/tests/test_cmd_chat.py` | Modify | Add one test for `session_writer` integration |

---

### Task 1: `sessions_dir` path helper + `SessionWriter`

**Files:**
- Modify: `cli/src/balu_code_cli/config/paths.py`
- Create: `cli/src/balu_code_cli/session/__init__.py`
- Create: `cli/src/balu_code_cli/session/writer.py`
- Create: `cli/tests/test_session_writer.py`

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_session_writer.py`:

```python
"""Tests for session/writer.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from balu_code_cli.config.paths import sessions_dir
from balu_code_cli.session.writer import SessionWriter


def test_sessions_dir_uses_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    d = sessions_dir("https://balu.example.com", 42)
    assert str(tmp_path) in str(d)
    assert "balu-code" in str(d)
    assert "sessions" in str(d)


def test_sessions_dir_falls_back_to_local_share(monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    d = sessions_dir("https://balu.example.com", 42)
    assert ".local/share/balu-code/sessions" in str(d)


def test_sessions_dir_same_url_project_same_hash():
    d1 = sessions_dir("https://balu.example.com", 1)
    d2 = sessions_dir("https://balu.example.com", 1)
    assert d1 == d2


def test_sessions_dir_different_project_different_hash():
    d1 = sessions_dir("https://balu.example.com", 1)
    d2 = sessions_dir("https://balu.example.com", 2)
    assert d1 != d2


def test_write_sent_creates_file(tmp_path):
    path = tmp_path / "session.jsonl"
    w = SessionWriter(path)
    w.write_sent({"type": "user_message", "content": "hello"})
    assert path.exists()
    line = json.loads(path.read_text().strip())
    assert line["direction"] == "out"
    assert line["payload"]["type"] == "user_message"
    assert "ts" in line


def test_write_event_appends_line(tmp_path):
    path = tmp_path / "session.jsonl"
    w = SessionWriter(path)

    class FakeEvent:
        def model_dump(self):
            return {"type": "token", "content": "hello"}

    w.write_event(FakeEvent())
    w.write_event(FakeEvent())
    lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    assert all(l["direction"] == "in" for l in lines)


def test_written_lines_are_valid_json(tmp_path):
    path = tmp_path / "session.jsonl"
    w = SessionWriter(path)
    w.write_sent({"type": "user_message", "content": "test"})

    class FakeEvent:
        def model_dump(self):
            return {"type": "turn_end", "turn_id": "t1", "total_tokens": 50,
                    "iterations": 1, "stop_reason": "done"}

    w.write_event(FakeEvent())
    for line in path.read_text().splitlines():
        obj = json.loads(line)
        assert "direction" in obj
        assert "ts" in obj
        assert "payload" in obj
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sven/projects/plugins/Balu_Code
python3 -m pytest cli/tests/test_session_writer.py -v 2>&1 | tail -20
```

Expected: FAIL — `ModuleNotFoundError: No module named 'balu_code_cli.session'`

- [ ] **Step 3: Add `sessions_dir` to `paths.py`**

Add to the end of `cli/src/balu_code_cli/config/paths.py` (before `__all__`):

```python
def sessions_dir(server_url: str, project_id: int) -> Path:
    import hashlib
    key = f"{server_url}:{project_id}".encode()
    h = hashlib.sha1(key, usedforsecurity=False).hexdigest()[:16]
    xdg = os.environ.get("XDG_DATA_HOME") or None
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "balu-code" / "sessions" / h
```

Update `__all__` to include `"sessions_dir"`.

- [ ] **Step 4: Create `cli/src/balu_code_cli/session/__init__.py`**

```python
"""Session storage — writer and reader for JSONL session files."""
```

- [ ] **Step 5: Create `cli/src/balu_code_cli/session/writer.py`**

```python
"""SessionWriter — appends WS events to a JSONL session file."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _event_to_dict(event: Any) -> dict:
    if hasattr(event, "model_dump"):
        return event.model_dump()
    if hasattr(event, "__dict__"):
        return vars(event)
    return {"raw": str(event)}


class SessionWriter:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh = None

    def _open(self) -> None:
        if self._fh is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self._path.open("a", encoding="utf-8")

    def _write(self, direction: str, payload: dict) -> None:
        self._open()
        line = json.dumps({
            "direction": direction,
            "ts": datetime.now(UTC).isoformat(),
            "payload": payload,
        })
        assert self._fh is not None
        self._fh.write(line + "\n")
        self._fh.flush()

    def write_sent(self, payload: dict) -> None:
        self._write("out", payload)

    def write_event(self, event: Any) -> None:
        self._write("in", _event_to_dict(event))

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
python3 -m pytest cli/tests/test_session_writer.py -v 2>&1 | tail -15
```

Expected: 8 passed

- [ ] **Step 7: Commit**

```bash
git add cli/src/balu_code_cli/config/paths.py \
        cli/src/balu_code_cli/session/__init__.py \
        cli/src/balu_code_cli/session/writer.py \
        cli/tests/test_session_writer.py
git commit -m "feat(cli): add sessions_dir path helper and SessionWriter"
```

---

### Task 2: `SessionReader`

**Files:**
- Create: `cli/src/balu_code_cli/session/reader.py`
- Create: `cli/tests/test_session_reader.py`

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_session_reader.py`:

```python
"""Tests for session/reader.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from balu_code_cli.session.reader import SessionReader


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def _entry(direction: str, payload: dict, ts: str = "2026-04-26T14:00:00+00:00") -> dict:
    return {"direction": direction, "ts": ts, "payload": payload}


def test_messages_single_turn(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_jsonl(path, [
        _entry("out", {"type": "user_message", "content": "hello"}),
        _entry("in", {"type": "turn_start", "turn_id": "t1", "model": "m", "context_tokens": 0}),
        _entry("in", {"type": "token", "content": "Hi "}),
        _entry("in", {"type": "token", "content": "there"}),
        _entry("in", {"type": "turn_end", "turn_id": "t1", "total_tokens": 10,
                      "iterations": 1, "stop_reason": "done"}),
    ])
    msgs = SessionReader(path).messages()
    assert msgs == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi there"},
    ]


def test_messages_multiple_turns(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_jsonl(path, [
        _entry("out", {"type": "user_message", "content": "q1"}),
        _entry("in", {"type": "token", "content": "a1"}),
        _entry("in", {"type": "turn_end", "turn_id": "t1", "total_tokens": 5,
                      "iterations": 1, "stop_reason": "done"}),
        _entry("out", {"type": "user_message", "content": "q2"}),
        _entry("in", {"type": "token", "content": "a2"}),
        _entry("in", {"type": "turn_end", "turn_id": "t2", "total_tokens": 5,
                      "iterations": 1, "stop_reason": "done"}),
    ])
    msgs = SessionReader(path).messages()
    assert msgs == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]


def test_messages_empty_file(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("")
    assert SessionReader(path).messages() == []


def test_metadata_turn_count(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_jsonl(path, [
        _entry("out", {"type": "user_message", "content": "q1"},
               ts="2026-04-26T10:00:00+00:00"),
        _entry("in", {"type": "turn_end", "turn_id": "t1", "total_tokens": 5,
                      "iterations": 1, "stop_reason": "done"}),
        _entry("out", {"type": "user_message", "content": "q2"}),
        _entry("in", {"type": "turn_end", "turn_id": "t2", "total_tokens": 5,
                      "iterations": 1, "stop_reason": "done"}),
    ])
    meta = SessionReader(path).metadata()
    assert meta["turn_count"] == 2
    assert meta["start_ts"] == "2026-04-26T10:00:00+00:00"


def test_metadata_empty_file(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("")
    meta = SessionReader(path).metadata()
    assert meta["turn_count"] == 0
    assert meta["start_ts"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest cli/tests/test_session_reader.py -v 2>&1 | tail -10
```

Expected: FAIL — `ModuleNotFoundError: No module named 'balu_code_cli.session.reader'`

- [ ] **Step 3: Create `cli/src/balu_code_cli/session/reader.py`**

```python
"""SessionReader — reconstructs messages and metadata from a JSONL session file."""

from __future__ import annotations

import json
from pathlib import Path


class SessionReader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def _lines(self) -> list[dict]:
        text = self._path.read_text(encoding="utf-8")
        return [json.loads(l) for l in text.splitlines() if l.strip()]

    def messages(self) -> list[dict]:
        result: list[dict] = []
        current_tokens: list[str] = []

        for entry in self._lines():
            direction = entry["direction"]
            payload = entry["payload"]
            event_type = payload.get("type")

            if direction == "out" and event_type == "user_message":
                if current_tokens:
                    result.append({"role": "assistant", "content": "".join(current_tokens)})
                    current_tokens = []
                result.append({"role": "user", "content": payload.get("content", "")})

            elif direction == "in" and event_type == "token":
                current_tokens.append(payload.get("content", ""))

            elif direction == "in" and event_type == "turn_end":
                if current_tokens:
                    result.append({"role": "assistant", "content": "".join(current_tokens)})
                    current_tokens = []

        if current_tokens:
            result.append({"role": "assistant", "content": "".join(current_tokens)})

        return result

    def metadata(self) -> dict:
        lines = self._lines()
        start_ts = lines[0]["ts"] if lines else None
        turn_count = sum(
            1 for e in lines
            if e["direction"] == "in" and e["payload"].get("type") == "turn_end"
        )
        return {"start_ts": start_ts, "turn_count": turn_count}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest cli/tests/test_session_reader.py -v 2>&1 | tail -10
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add cli/src/balu_code_cli/session/reader.py cli/tests/test_session_reader.py
git commit -m "feat(cli): add SessionReader"
```

---

### Task 3: Wire `SessionWriter` into `chat.py`

**Files:**
- Modify: `cli/src/balu_code_cli/commands/chat.py`
- Modify: `cli/tests/test_cmd_chat.py`

Context on `chat.py` as it exists: `run_chat(balucode, api_key, yolo, project_id, ws_factory=None, input_fn=_default_input, perms_path=None)` and `_dispatch_turn(ws, balucode, yolo, permissions, perms_path, input_fn)`.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_cmd_chat.py` at the bottom (after the existing imports, which already include `from unittest.mock import AsyncMock, MagicMock`):

```python
@pytest.mark.asyncio
async def test_run_chat_writes_session_events(tmp_path):
    from unittest.mock import MagicMock
    from balu_code_cli.session.writer import SessionWriter

    writer = MagicMock(spec=SessionWriter)

    events = [
        _make_event("turn_start", turn_id="t1", model="m", context_tokens=0),
        _make_event("token", content="hi"),
        _make_event("turn_end", turn_id="t1", total_tokens=5, iterations=1, stop_reason="done"),
    ]
    fake_ws = _make_ws(events)

    async def fake_input(prompt=""):
        raise EOFError

    await run_chat(
        balucode=_BALUCODE,
        api_key="k",
        yolo=False,
        project_id=1,
        ws_factory=_make_factory(fake_ws),
        input_fn=fake_input,
        perms_path=tmp_path / "perms.yaml",
        session_writer=writer,
    )
    assert writer.write_event.call_count == 3
```

Note: `_make_event`, `_make_ws`, `_make_factory` are helpers already present in `test_cmd_chat.py`. Verify their names by reading the file first — use whatever the existing helpers are called.

- [ ] **Step 2: Read existing test helpers**

Read `cli/tests/test_cmd_chat.py` to find the exact names of the WS/event mock helpers already used in the streaming tests. The new test must use the same helpers.

- [ ] **Step 3: Run test to verify it fails**

```bash
python3 -m pytest cli/tests/test_cmd_chat.py::test_run_chat_writes_session_events -v 2>&1 | tail -10
```

Expected: FAIL — `run_chat() got an unexpected keyword argument 'session_writer'`

- [ ] **Step 4: Modify `chat.py`**

Add `session_writer` import at top of `cli/src/balu_code_cli/commands/chat.py`:

```python
from __future__ import annotations

import asyncio
import getpass
import json as _json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel

from balu_code_cli.client.ws import BaluCodeWS, connect
from balu_code_cli.config.balucode_yaml import BaluCodeYaml, load_balucode_yaml
from balu_code_cli.config.loader import load_credentials
from balu_code_cli.config.paths import permissions_yaml as _permissions_yaml
from balu_code_cli.config.paths import sessions_dir as _sessions_dir
from balu_code_cli.config.permissions import PermissionsStore, load_permissions, save_permissions
from balu_code_cli.session.writer import SessionWriter
```

Change `_dispatch_turn` signature to add `session_writer`:

```python
async def _dispatch_turn(
    ws: BaluCodeWS,
    balucode: BaluCodeYaml,
    yolo: bool,
    permissions: PermissionsStore,
    perms_path: Path,
    input_fn: InputFn,
    session_writer: SessionWriter | None = None,
) -> str | None:
    turn_id = None

    while True:
        event = await ws.receive()
        if session_writer:
            session_writer.write_event(event)

        if event.type == "turn_start":
            turn_id = event.turn_id
        # ... rest unchanged
```

Change `run_chat` signature and body:

```python
async def run_chat(
    balucode: BaluCodeYaml,
    api_key: str,
    yolo: bool,
    project_id: int,
    ws_factory=None,
    input_fn: InputFn = _default_input,
    perms_path: Path | None = None,
    session_writer: SessionWriter | None = None,
    initial_messages: list[dict] | None = None,
) -> None:
    _connect = ws_factory or connect
    _perms_path = perms_path or _permissions_yaml()
    permissions = load_permissions(_perms_path)

    async with _connect(balucode.server_url, api_key, project_id) as ws:
        if initial_messages:
            console.print("[dim]── resumed session ──[/dim]")
            for msg in initial_messages:
                if msg["role"] == "user":
                    console.print(f"[bold cyan][balu-code] >[/bold cyan] {msg['content']}")
                else:
                    console.print(msg["content"])
            console.print("[dim]── continuing ──[/dim]")

        while True:
            try:
                line = await input_fn("[balu-code] > ")
            except (EOFError, KeyboardInterrupt):
                break

            line = line.strip()
            if not line:
                continue
            if line in (".exit", ".quit"):
                break

            await ws.send_message(line)
            if session_writer:
                session_writer.write_sent({"type": "user_message", "content": line})
            turn_id = None
            try:
                turn_id = await _dispatch_turn(
                    ws, balucode, yolo, permissions, _perms_path, input_fn, session_writer
                )
            except KeyboardInterrupt:
                if turn_id:
                    await ws.send_cancel(turn_id)
                    console.print("[yellow]Cancelled[/yellow]")
```

Change the `chat` command to auto-create a `SessionWriter`:

```python
@app.callback(invoke_without_command=True)
def chat(
    yolo: bool = typer.Option(False, "--yolo", help="Auto-approve all tool calls."),
    project_id: int | None = typer.Option(None, "--project-id", help="Override project ID."),
) -> None:
    """Start an interactive chat REPL."""
    try:
        balucode = load_balucode_yaml()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None

    creds = load_credentials()
    if balucode.server_url not in creds.servers:
        console.print("[red]Not logged in. Run `balu-code auth login` first.[/red]")
        raise typer.Exit(1)

    api_key = creds.servers[balucode.server_url].api_key
    pid = project_id or balucode.project_id

    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    user = getpass.getuser()
    uid = str(uuid.uuid4())
    sess_path = _sessions_dir(balucode.server_url, pid) / f"{ts}_{user}_{uid}.jsonl"
    writer = SessionWriter(sess_path)

    asyncio.run(run_chat(
        balucode=balucode,
        api_key=api_key,
        yolo=yolo,
        project_id=pid,
        session_writer=writer,
    ))
```

- [ ] **Step 5: Run all chat tests to verify they pass**

```bash
python3 -m pytest cli/tests/test_cmd_chat.py -v 2>&1 | tail -15
```

Expected: 10 passed (9 existing + 1 new)

- [ ] **Step 6: Commit**

```bash
git add cli/src/balu_code_cli/commands/chat.py cli/tests/test_cmd_chat.py
git commit -m "feat(cli): auto-save sessions in chat REPL via SessionWriter"
```

---

### Task 4: `commands/session.py`

**Files:**
- Create: `cli/src/balu_code_cli/commands/session.py`
- Create: `cli/tests/test_cmd_session.py`

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_cmd_session.py`:

```python
"""Tests for commands/session.py."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from balu_code_cli.commands.session import app

runner = CliRunner()

_BALUCODE_YAML = "project_id: 1\nserver_url: https://balu.example.com\n"


def _make_session_dir(tmp_path: Path) -> Path:
    from balu_code_cli.config.paths import sessions_dir
    d = sessions_dir("https://balu.example.com", 1)
    # Override to use tmp_path
    real_dir = tmp_path / "sessions" / "abc123"
    real_dir.mkdir(parents=True)
    return real_dir


def _write_session(sess_dir: Path, filename: str, turns: int = 2) -> Path:
    path = sess_dir / filename
    lines = []
    for i in range(turns):
        lines.append(json.dumps({
            "direction": "out",
            "ts": f"2026-04-26T1{i}:00:00+00:00",
            "payload": {"type": "user_message", "content": f"q{i}"},
        }))
        lines.append(json.dumps({
            "direction": "in",
            "ts": f"2026-04-26T1{i}:00:01+00:00",
            "payload": {"type": "token", "content": f"a{i}"},
        }))
        lines.append(json.dumps({
            "direction": "in",
            "ts": f"2026-04-26T1{i}:00:02+00:00",
            "payload": {"type": "turn_end", "turn_id": f"t{i}",
                        "total_tokens": 10, "iterations": 1, "stop_reason": "done"},
        }))
    path.write_text("\n".join(lines) + "\n")
    return path


def test_session_list_no_sessions(tmp_path):
    balucode_file = tmp_path / ".balucode.yaml"
    balucode_file.write_text(_BALUCODE_YAML)
    with patch("balu_code_cli.commands.session.load_balucode_yaml") as mock_load, \
         patch("balu_code_cli.commands.session.sessions_dir") as mock_dir:
        from balu_code_cli.config.balucode_yaml import BaluCodeYaml
        mock_load.return_value = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")
        mock_dir.return_value = tmp_path / "empty_sessions"
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No sessions" in result.output


def test_session_list_shows_sessions(tmp_path):
    from balu_code_cli.config.balucode_yaml import BaluCodeYaml
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    _write_session(sess_dir, "2026-04-26T14-00-00_sven_aaaabbbb-0000-0000-0000-000000000001.jsonl", turns=2)
    _write_session(sess_dir, "2026-04-25T09-00-00_sven_aaaabbbb-0000-0000-0000-000000000002.jsonl", turns=5)
    with patch("balu_code_cli.commands.session.load_balucode_yaml") as mock_load, \
         patch("balu_code_cli.commands.session.sessions_dir") as mock_dir:
        mock_load.return_value = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")
        mock_dir.return_value = sess_dir
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "2" in result.output  # turn count
    assert "5" in result.output


def test_session_delete_confirmed(tmp_path):
    from balu_code_cli.config.balucode_yaml import BaluCodeYaml
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    sess_file = _write_session(
        sess_dir, "2026-04-26T14-00-00_sven_deadbeef-0000-0000-0000-000000000001.jsonl"
    )
    with patch("balu_code_cli.commands.session.load_balucode_yaml") as mock_load, \
         patch("balu_code_cli.commands.session.sessions_dir") as mock_dir:
        mock_load.return_value = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")
        mock_dir.return_value = sess_dir
        result = runner.invoke(app, ["delete", "deadbeef"], input="y\n")
    assert result.exit_code == 0
    assert not sess_file.exists()


def test_session_delete_aborted(tmp_path):
    from balu_code_cli.config.balucode_yaml import BaluCodeYaml
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    sess_file = _write_session(
        sess_dir, "2026-04-26T14-00-00_sven_deadbeef-0000-0000-0000-000000000001.jsonl"
    )
    with patch("balu_code_cli.commands.session.load_balucode_yaml") as mock_load, \
         patch("balu_code_cli.commands.session.sessions_dir") as mock_dir:
        mock_load.return_value = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")
        mock_dir.return_value = sess_dir
        result = runner.invoke(app, ["delete", "deadbeef"], input="N\n")
    assert result.exit_code == 0
    assert sess_file.exists()


def test_session_resume_calls_run_chat_with_initial_messages(tmp_path):
    from balu_code_cli.config.balucode_yaml import BaluCodeYaml
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    _write_session(
        sess_dir, "2026-04-26T14-00-00_sven_cafebabe-0000-0000-0000-000000000001.jsonl", turns=1
    )
    creds_yaml = "servers:\n  https://balu.example.com:\n    api_key: testkey\n"
    with patch("balu_code_cli.commands.session.load_balucode_yaml") as mock_load, \
         patch("balu_code_cli.commands.session.sessions_dir") as mock_dir, \
         patch("balu_code_cli.commands.session.load_credentials") as mock_creds, \
         patch("balu_code_cli.commands.session.run_chat") as mock_run:
        from balu_code_cli.config.loader import Credentials, ServerCredentials
        mock_load.return_value = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")
        mock_dir.return_value = sess_dir
        mock_creds.return_value = Credentials(
            servers={"https://balu.example.com": ServerCredentials(api_key="testkey")}
        )
        mock_run.return_value = None
        result = runner.invoke(app, ["resume", "cafebabe"])
    assert result.exit_code == 0
    call_kwargs = mock_run.call_args.kwargs
    assert "initial_messages" in call_kwargs
    assert len(call_kwargs["initial_messages"]) >= 1


def test_session_resume_ambiguous_prefix(tmp_path):
    from balu_code_cli.config.balucode_yaml import BaluCodeYaml
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    _write_session(sess_dir, "2026-04-26T14-00-00_sven_aabbccdd-1111-0000-0000-000000000001.jsonl")
    _write_session(sess_dir, "2026-04-26T15-00-00_sven_aabbccdd-2222-0000-0000-000000000002.jsonl")
    with patch("balu_code_cli.commands.session.load_balucode_yaml") as mock_load, \
         patch("balu_code_cli.commands.session.sessions_dir") as mock_dir:
        mock_load.return_value = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")
        mock_dir.return_value = sess_dir
        result = runner.invoke(app, ["resume", "aabbccdd"])
    assert result.exit_code != 0
    assert "Ambiguous" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest cli/tests/test_cmd_session.py -v 2>&1 | tail -10
```

Expected: FAIL — `ModuleNotFoundError` or import error

- [ ] **Step 3: Create `cli/src/balu_code_cli/commands/session.py`**

```python
"""session list / resume / delete commands."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from balu_code_cli.commands.chat import run_chat
from balu_code_cli.config.balucode_yaml import load_balucode_yaml
from balu_code_cli.config.loader import load_credentials
from balu_code_cli.config.paths import sessions_dir
from balu_code_cli.session.reader import SessionReader

app = typer.Typer(help="Manage chat sessions.")
console = Console()


def _find_session(sess_dir: Path, id_prefix: str) -> Path:
    matches = [f for f in sess_dir.glob("*.jsonl") if id_prefix in f.stem]
    if not matches:
        console.print(f"[red]No session matches prefix '{id_prefix}'[/red]")
        raise typer.Exit(1)
    if len(matches) > 1:
        names = ", ".join(f.name for f in matches)
        console.print(f"[red]Ambiguous prefix — matches: {names}[/red]")
        raise typer.Exit(1)
    return matches[0]


@app.command("list")
def session_list() -> None:
    """List sessions for the current project."""
    try:
        balucode = load_balucode_yaml()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None

    sess_dir = sessions_dir(balucode.server_url, balucode.project_id)
    if not sess_dir.exists():
        console.print("No sessions yet.")
        return

    files = sorted(sess_dir.glob("*.jsonl"), reverse=True)
    if not files:
        console.print("No sessions yet.")
        return

    table = Table(title="Sessions")
    table.add_column("Timestamp")
    table.add_column("Turns", justify="right")
    table.add_column("ID (prefix)")

    for f in files:
        reader = SessionReader(f)
        meta = reader.metadata()
        ts_raw = meta["start_ts"]
        ts = ts_raw[:16].replace("T", " ") if ts_raw else "?"
        # filename: <ts>_<user>_<uuid>.jsonl — split on "_" max 2 times
        parts = f.stem.split("_", 2)
        uid_prefix = parts[2][:8] if len(parts) >= 3 else f.stem[:8]
        table.add_row(ts, str(meta["turn_count"]), uid_prefix)

    console.print(table)


@app.command("resume")
def session_resume(
    id_prefix: str = typer.Argument(..., help="UUID prefix of the session to resume."),
) -> None:
    """Resume a previous chat session."""
    try:
        balucode = load_balucode_yaml()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None

    creds = load_credentials()
    if balucode.server_url not in creds.servers:
        console.print("[red]Not logged in. Run `balu-code auth login` first.[/red]")
        raise typer.Exit(1)

    sess_dir = sessions_dir(balucode.server_url, balucode.project_id)
    session_path = _find_session(sess_dir, id_prefix)
    initial_messages = SessionReader(session_path).messages()

    api_key = creds.servers[balucode.server_url].api_key
    asyncio.run(run_chat(
        balucode=balucode,
        api_key=api_key,
        yolo=False,
        project_id=balucode.project_id,
        initial_messages=initial_messages,
    ))


@app.command("delete")
def session_delete(
    id_prefix: str = typer.Argument(..., help="UUID prefix of the session to delete."),
) -> None:
    """Delete a session."""
    try:
        balucode = load_balucode_yaml()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None

    sess_dir = sessions_dir(balucode.server_url, balucode.project_id)
    session_path = _find_session(sess_dir, id_prefix)

    confirmed = typer.confirm(f"Really delete {session_path.name}?", default=False)
    if confirmed:
        session_path.unlink()
        console.print("[green]Deleted.[/green]")
    else:
        console.print("Aborted.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest cli/tests/test_cmd_session.py -v 2>&1 | tail -15
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add cli/src/balu_code_cli/commands/session.py cli/tests/test_cmd_session.py
git commit -m "feat(cli): add session list / resume / delete commands"
```

---

### Task 5: `commands/config.py`

**Files:**
- Create: `cli/src/balu_code_cli/commands/config.py`
- Create: `cli/tests/test_cmd_config.py`

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_cmd_config.py`:

```python
"""Tests for commands/config.py."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from balu_code_cli.commands.config import app
from balu_code_cli.config.loader import AppConfig, save_config

runner = CliRunner()


def test_config_get_server_url(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    save_config(AppConfig(server_url="https://example.com"), path=cfg_path)
    from unittest.mock import patch
    with patch("balu_code_cli.commands.config.load_config",
               return_value=AppConfig(server_url="https://example.com")):
        result = runner.invoke(app, ["get", "server_url"])
    assert result.exit_code == 0
    assert "https://example.com" in result.output


def test_config_get_unknown_key():
    result = runner.invoke(app, ["get", "nonexistent_key"])
    assert result.exit_code != 0
    assert "Unknown key" in result.output
    assert "server_url" in result.output


def test_config_set_default_project_id(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    from unittest.mock import patch, MagicMock
    saved = {}

    def fake_save(cfg, path=None):
        saved["cfg"] = cfg

    with patch("balu_code_cli.commands.config.load_config", return_value=AppConfig()), \
         patch("balu_code_cli.commands.config.save_config", side_effect=fake_save):
        result = runner.invoke(app, ["set", "default_project_id", "7"])
    assert result.exit_code == 0
    assert saved["cfg"].default_project_id == 7


def test_config_set_server_url(tmp_path):
    saved = {}

    def fake_save(cfg, path=None):
        saved["cfg"] = cfg

    from unittest.mock import patch
    with patch("balu_code_cli.commands.config.load_config", return_value=AppConfig()), \
         patch("balu_code_cli.commands.config.save_config", side_effect=fake_save):
        result = runner.invoke(app, ["set", "server_url", "https://new.example.com"])
    assert result.exit_code == 0
    assert saved["cfg"].server_url == "https://new.example.com"


def test_config_set_type_error_for_project_id():
    from unittest.mock import patch
    with patch("balu_code_cli.commands.config.load_config", return_value=AppConfig()):
        result = runner.invoke(app, ["set", "default_project_id", "notanumber"])
    assert result.exit_code != 0
    assert "integer" in result.output.lower()


def test_config_set_unknown_key():
    result = runner.invoke(app, ["set", "nonexistent_key", "value"])
    assert result.exit_code != 0
    assert "Unknown key" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest cli/tests/test_cmd_config.py -v 2>&1 | tail -10
```

Expected: FAIL — `ModuleNotFoundError: No module named 'balu_code_cli.commands.config'`

- [ ] **Step 3: Create `cli/src/balu_code_cli/commands/config.py`**

```python
"""config get / set commands."""

from __future__ import annotations

import typer
from rich.console import Console

from balu_code_cli.config.loader import AppConfig, load_config, save_config

app = typer.Typer(help="Get or set CLI configuration values.")
console = Console()

_VALID_KEYS = frozenset({"server_url", "default_project_id"})


@app.command("get")
def config_get(key: str = typer.Argument(..., help="Config key to read.")) -> None:
    """Print the current value of a config key."""
    if key not in _VALID_KEYS:
        console.print(
            f"[red]Unknown key '{key}'. Valid keys: {', '.join(sorted(_VALID_KEYS))}[/red]"
        )
        raise typer.Exit(1)
    cfg = load_config()
    value = getattr(cfg, key)
    typer.echo("" if value is None else str(value))


@app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key to update."),
    value: str = typer.Argument(..., help="New value."),
) -> None:
    """Set a config key to a new value."""
    if key not in _VALID_KEYS:
        console.print(
            f"[red]Unknown key '{key}'. Valid keys: {', '.join(sorted(_VALID_KEYS))}[/red]"
        )
        raise typer.Exit(1)

    cfg = load_config()
    if key == "default_project_id":
        try:
            setattr(cfg, key, int(value))
        except ValueError:
            console.print(f"[red]Expected integer for {key}[/red]")
            raise typer.Exit(1) from None
    else:
        setattr(cfg, key, value)

    save_config(cfg)
    console.print(f"[green]{key} = {value}[/green]")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest cli/tests/test_cmd_config.py -v 2>&1 | tail -10
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add cli/src/balu_code_cli/commands/config.py cli/tests/test_cmd_config.py
git commit -m "feat(cli): add config get / set commands"
```

---

### Task 6: Wire into `__main__.py` + full verification

**Files:**
- Modify: `cli/src/balu_code_cli/__main__.py`

- [ ] **Step 1: Update `__main__.py`**

Replace the full content of `cli/src/balu_code_cli/__main__.py`:

```python
"""Typer entry point for `balu-code`."""

from __future__ import annotations

import typer

from balu_code_cli import __version__
from balu_code_cli.commands.auth import app as auth_app
from balu_code_cli.commands.chat import app as chat_app
from balu_code_cli.commands.config import app as config_app
from balu_code_cli.commands.index import app as index_app
from balu_code_cli.commands.init import app as init_app
from balu_code_cli.commands.models import app as models_app
from balu_code_cli.commands.session import app as session_app

app = typer.Typer(
    name="balu-code",
    no_args_is_help=True,
    add_completion=False,
    help="Balu Code — self-hosted coding agent.",
)
app.add_typer(auth_app, name="auth")
app.add_typer(init_app, name="init")
app.add_typer(models_app, name="models")
app.add_typer(index_app, name="index")
app.add_typer(chat_app, name="chat")
app.add_typer(session_app, name="session")
app.add_typer(config_app, name="config")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"balu-code {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Balu Code terminal client."""
```

- [ ] **Step 2: Run the full CLI test suite**

```bash
python3 -m pytest cli/tests/ -q 2>&1 | tail -10
```

Expected: all pass (66+ tests)

- [ ] **Step 3: Run ruff on all CLI source**

```bash
python3 -m ruff check cli/src/balu_code_cli/ 2>&1
```

Expected: `All checks passed!`

If violations appear, fix them (most common: `B904` on `raise typer.Exit(1)` in except blocks → add `from None`; `I001` import sort → run `ruff check --fix`).

- [ ] **Step 4: Smoke-test `--help` shows all commands**

```bash
PYTHONPATH=/home/sven/projects/plugins/Balu_Code/cli/src:/home/sven/projects/plugins/Balu_Code/shared/src \
  python3 -c "
from balu_code_cli.__main__ import app
from typer.testing import CliRunner
r = CliRunner()
print(r.invoke(app, ['--help']).output)
"
```

Expected: shows `auth`, `init`, `models`, `index`, `chat`, `session`, `config` in Commands section.

- [ ] **Step 5: Commit and push**

```bash
git add cli/src/balu_code_cli/__main__.py
git commit -m "feat(cli): wire session + config commands into __main__.py"
git push origin main
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `sessions_dir(server_url, project_id)` XDG-aware | Task 1 |
| `SessionWriter` appends JSONL with `direction`/`ts`/`payload` | Task 1 |
| `SessionReader.messages()` reconstructs user+assistant pairs | Task 2 |
| `SessionReader.metadata()` returns `start_ts`, `turn_count` | Task 2 |
| Auto-save in `chat` REPL | Task 3 |
| `initial_messages` display on resume | Task 3 |
| `session list` — table with timestamp, turns, ID prefix | Task 4 |
| `session resume <prefix>` — loads messages, starts REPL | Task 4 |
| `session delete <prefix>` — confirm + delete | Task 4 |
| Ambiguous prefix error | Task 4 |
| `config get <key>` | Task 5 |
| `config set <key> <value>` | Task 5 |
| Unknown key error with valid key list | Task 5 |
| Type mismatch error for `default_project_id` | Task 5 |
| Wire into `__main__.py` | Task 6 |
| Ruff clean | Task 6 |

All spec requirements covered. No placeholders. Method names are consistent across all tasks.
