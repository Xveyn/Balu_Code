# Balu Code Phase 5b — Session Storage + Config Commands Design

## Goal

Add automatic client-side session persistence to the `chat` REPL and two new top-level command groups: `session` (list / resume / delete) and `config` (get / set).

## Architecture

### New files

```
cli/src/balu_code_cli/
  session/
    __init__.py
    writer.py      # SessionWriter — writes WS events as JSONL lines
    reader.py      # SessionReader — reads JSONL, reconstructs messages[]
  commands/
    session.py     # session list / resume / delete
    config.py      # config get / set
```

### Existing files modified

- `cli/src/balu_code_cli/commands/chat.py` — `run_chat()` gets a new optional `session_writer: SessionWriter | None` parameter; the function writes each outgoing and incoming frame via the writer when present. Auto-creates a writer on every real invocation.
- `cli/src/balu_code_cli/__main__.py` — registers `session_app` and `config_app`.
- `cli/src/balu_code_cli/config/paths.py` — adds `sessions_dir(server_url, project_id) -> Path` helper.

## Session Storage

**Directory:** `~/.local/share/balu-code/sessions/<sha1(server_url + ":" + str(project_id))>/`

**Filename:** `<ISO-8601-timestamp>-<local-username>-<uuid4>.jsonl`

Example: `2026-04-26T14-32-05-sven-a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl`

**Line format** — one JSON object per line:

```json
{"direction": "out", "ts": "2026-04-26T14:32:05.123Z", "payload": {"type": "user_message", "content": "fix the null pointer"}}
{"direction": "in",  "ts": "2026-04-26T14:32:05.456Z", "payload": {"type": "turn_start", "turn_id": "t-abc"}}
{"direction": "in",  "ts": "2026-04-26T14:32:06.001Z", "payload": {"type": "token", "content": "Sure,"}}
```

Every outgoing frame (`send_message`, `send_approval`, `send_cancel`) and every incoming event is written as a line. The file grows append-only during the session.

## Components

### `session/writer.py` — `SessionWriter`

```python
class SessionWriter:
    def __init__(self, path: Path) -> None: ...
    def write_sent(self, payload: dict) -> None: ...   # direction="out"
    def write_event(self, event: Any) -> None: ...     # direction="in"
```

Opens the file on first write (lazy), appends JSON lines with a UTC timestamp. Thread-safe write not required (single async task).

### `session/reader.py` — `SessionReader`

```python
class SessionReader:
    def __init__(self, path: Path) -> None: ...
    def messages(self) -> list[dict]: ...
    # Returns [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
    # Reconstructs from: out user_message → role=user; in token frames concatenated per turn → role=assistant
    def metadata(self) -> dict: ...
    # Returns {"start_ts": str, "turn_count": int, "project_id": int | None}
```

`messages()` scans the JSONL once:
- `direction=out, type=user_message` → new user entry
- `direction=in, type=token` → accumulate into current assistant entry
- `direction=in, type=turn_end` → flush assistant entry

### `commands/session.py`

**`session list`**

Reads `.balucode.yaml` for `server_url` + `project_id`, resolves the session directory via `sessions_dir()`, scans all `.jsonl` files, calls `SessionReader.metadata()` on each, prints a Rich table sorted by timestamp descending:

```
 Timestamp            Turns  ID (prefix)
 2026-04-26 14:32      3     a1b2c3d4
 2026-04-25 09:11      7     e5f6g7h8
```

**`session resume <id-prefix>`**

Finds the matching JSONL file by UUID prefix (errors if 0 or >1 match), calls `SessionReader.messages()`, starts `run_chat()` with `initial_messages=messages`.

**`session delete <id-prefix>`**

Finds the file, prompts `Really delete? [y/N]`, deletes on confirmation.

### `commands/config.py`

**`config get <key>`**

Prints the current value of an `AppConfig` field. Valid keys: `server_url`, `default_project_id`. Unknown key → error listing valid keys.

**`config set <key> <value>`**

Parses `value` (int for `default_project_id`, str for `server_url`), writes updated `AppConfig` to `~/.config/balu-code/config.yaml`.

### `commands/chat.py` — changes

`run_chat()` gains a new parameter:

```python
async def run_chat(
    ...
    session_writer: SessionWriter | None = None,
) -> None:
```

If `session_writer` is `None`, the `chat` command auto-creates one using `sessions_dir()` + a fresh filename. The writer is called:
- After `ws.send_message(line)` → `session_writer.write_sent({"type": "user_message", "content": line})`
- After `ws.send_approval(...)` → `session_writer.write_sent({...})`
- After `ws.send_cancel(...)` → `session_writer.write_sent({...})`
- In `_dispatch_turn` after every `ws.receive()` call → `session_writer.write_event(event)`

`_dispatch_turn` also gains `session_writer` as a parameter (passed through from `run_chat`).

`run_chat()` also gains `initial_messages: list[dict] | None = None` for resume support. When set, these messages are passed to `ws.send_message()` as a `context` field alongside the new user message — the server receives them as prior conversation history prepended to the current turn. No new WS frame types are needed; the existing `user_message` payload gains an optional `context: list[dict]` field.

## `config/paths.py` — new helper

```python
def sessions_dir(server_url: str, project_id: int) -> Path:
    import hashlib, os
    key = f"{server_url}:{project_id}".encode()
    h = hashlib.sha1(key).hexdigest()[:16]
    xdg = os.environ.get("XDG_DATA_HOME") or None
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "balu-code" / "sessions" / h
```

## Error Handling

- Session directory does not exist → `session list` prints "No sessions yet." (no error)
- Resume prefix matches 0 files → error "No session matches prefix '<x>'"
- Resume prefix matches >1 files → error "Ambiguous prefix — matches: ..."
- `config get` unknown key → error "Unknown key '<k>'. Valid keys: server_url, default_project_id"
- `config set` type mismatch (e.g. `default_project_id abc`) → error "Expected integer for default_project_id"

## Testing

**`tests/test_session_writer.py`**
- `test_write_sent_creates_file` — call `write_sent`, assert JSONL file created with `direction=out`
- `test_write_event_appends` — two events, assert two lines
- `test_written_lines_are_valid_json` — parse each line

**`tests/test_session_reader.py`**
- `test_messages_reconstructs_turns` — JSONL with 1 user + 3 token frames + turn_end → `[user, assistant]`
- `test_messages_multiple_turns` — 2 user messages → 2 user + 2 assistant entries
- `test_metadata_turn_count` — JSONL with 2 turn_end events → `turn_count=2`

**`tests/test_cmd_session.py`**
- `test_session_list_empty` — no JSONL files → "No sessions yet."
- `test_session_list_shows_sessions` — 2 JSONL files → table with 2 rows
- `test_session_resume_calls_run_chat_with_messages` — mock `run_chat`, assert `initial_messages` passed
- `test_session_resume_ambiguous_prefix` — 2 files with same prefix → error
- `test_session_delete_confirmed` — file deleted after `y`
- `test_session_delete_aborted` — file kept after `N`

**`tests/test_cmd_config.py`**
- `test_config_get_server_url` — existing config → prints value
- `test_config_set_default_project_id` — writes int to YAML
- `test_config_get_unknown_key` — error with valid key list
- `test_config_set_type_error` — `set default_project_id abc` → error

**`tests/test_cmd_chat.py` additions**
- `test_run_chat_writes_session_events` — mock `SessionWriter`, assert `write_sent` and `write_event` called

## Constraints

- No server-side changes. Server remains stateless per turn.
- Resume injects prior messages client-side only; the server sees them as fresh context.
- No session index file — disk scan on `list` is sufficient for single-user v1.
- `initial_messages` resume: exact WS framing (how prior messages are sent as context) follows the existing `messages` array in the current protocol. No new frame types needed.
