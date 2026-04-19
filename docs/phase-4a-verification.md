# Phase 4a verification — 2026-04-19

## Environment (local dev)

- Commit: `8d108a1`
- Python: 3.13.5 (CI matrix covers 3.11 & 3.12)

## Automated checks

- [x] `ruff check .` — clean
- [x] `ruff format --check .` — clean (72 files)
- [x] `pytest -v` — 248 tests passing (up from 216 at end of Phase 3b, +32)
- [x] `.bhplugin` includes all Phase-4a service modules + both prompt files (37 files total)
- [x] `python -m scripts.build_wheel` still produces `balu_code_cli-0.1.0-py3-none-any.whl`
- [x] GitHub Actions: CI green on `main` — https://github.com/Xveyn/Balu_Code/actions/runs/24637491851

## Manual checks against dev BaluHost

- [ ] Re-sideload the new `.bhplugin`.
- [ ] BaluHost venv installs `tiktoken`.
- [ ] Restart the BaluHost backend.
- [ ] Connect a WebSocket to `/api/plugins/balu_code/chat?project_id=<id>`,
      send a `user_message`, observe `turn_start` → tokens → `turn_end`.
- [ ] Ask a question that requires `read_file` (e.g. "What does foo.py do?");
      confirm `tool_call` + `tool_result` frames with `auto_approved: true`.

## Plan deviations

Between Task 10 baseline (`10b0b6c`) and HEAD (`8d108a1`):

- `891e3ee` — follow-up to Task 11 addressing a code-review finding: `total_tokens` was not counting tool-result bytes, neutering the `max_total_tokens_per_turn` guard. Now counted when appending each tool message.
- `8d108a1` — `ruff format` pass across the 16 Phase-4a files; ruff-check was clean throughout but format was only verified at Task 14.
- Task 11 `_iteration` rename: `for iteration in range(...)` → `for _iteration in range(...)` to silence `B007` ruff warning (unused loop variable; the `iterations` counter is kept separately).

## Known issues carried into Phase 4b

- No write-side tools yet (`write_file`, `apply_patch`, `run_bash`, `web_fetch`).
- No `approval_request` / `approval` / `cancel` frames — cannot interrupt a turn.
- Path-containment is inline in `read_file.py`; extract to `plugin/services/paths.py` with 4b.
- Audit log not wired.
- Tokenizer is cl100k_base — ~15% error against qwen's real tokenizer. Acceptable for budgeting.
- Token-cap (`max_total_tokens_per_turn`) hit emits `stop_reason="max_iter"`, overloading that literal. Adding a distinct `"max_tokens"` stop reason requires an events-schema change; deferred to 4b alongside the cancel/approval frames.
- Context is assembled once per turn; re-sent context on subsequent iterations of the same turn is not re-counted into `total_tokens`. Minor undercount in multi-iteration tool-heavy turns.
