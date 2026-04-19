# Phase 3b verification — 2026-04-19

## Environment (local dev)

- Commit: `31b6db6` (post-format-cleanup on top of the Phase-3b feat commits)
- Python: 3.13.5 (CI matrix covers 3.11 & 3.12)

## Automated checks

- [x] `ruff check .` — clean
- [x] `ruff format --check .` — clean (56 files already formatted)
- [x] `pytest -v` — **194** tests passing (0 skipped, 7.18 s)
- [x] `.bhplugin` includes `services/rag_chunker.py`, `services/rag_index.py`,
      `services/rag_registry.py`, `services/index_jobs.py`,
      `services/indexer.py`, plus prior Phase modules
      (27 files total in archive)
- [x] `python -m scripts.build_wheel` still produces the CLI wheel
- [x] GitHub Actions: CI green on `main` — run [24629388171](https://github.com/Xveyn/Balu_Code/actions/runs/24629388171), both py 3.11 and py 3.12 green in ~35 s

## dist/ artefacts

```
balu_code-0.1.0.bhplugin
balu_code-0.1.0.bhplugin.sha256
balu_code_cli-0.1.0-py3-none-any.whl
```

## Manual checks against dev BaluHost

- [ ] Re-sideload the new `.bhplugin` into
      `/opt/baluhost/backend/app/plugins/installed/balu_code/`
- [ ] BaluHost venv installs `sqlite-vec`
- [ ] Restart the BaluHost backend
- [ ] `POST /api/plugins/balu_code/projects/{id}/index` returns 202 + job_id
- [ ] `GET /api/plugins/balu_code/projects/{id}/index/status/{job_id}`
      transitions from `queued` → `running` → `done` with non-zero
      `files_processed` on a real Python project
- [ ] Re-POSTing while job is running returns 409

## Plan deviations

Commits since `5f024ba` (Phase 3b start), excluding the planned `feat:` tasks:

- `refactor(plugin): promote IGNORE_DIRS and get_parser to public API` —
  needed by the indexer worker to walk the repo map correctly; not originally
  called out as a separate task.
- `refactor(plugin): tighten RagIndex open path + clear rows on empty upsert` —
  follow-up fix after RagIndex storage landed; clears stale rows when a
  re-index produces an empty chunk set instead of leaving orphans.
- `test(plugin): run index polling test via httpx.AsyncClient instead of TestClient` —
  the `starlette.testclient.TestClient` blocks the event loop, which deadlocks
  the background indexer task; switched to `httpx.AsyncClient` with the
  `asgi` transport so the test can actually observe `queued → running → done`.
- `style: ruff format auto-fixes + gitignore .claude/` — cleanup commit after
  the initial verification doc push failed CI because the working tree had
  uncommitted `ruff format` auto-fixes. Also gitignored the Claude-Code
  session-state dir so future runs don't leak stray `.claude/` files into
  the repo.

All other commits are direct `feat:` deliverables from the Phase 3b task list.

## Known issues carried into Phase 4

- HTTP `/search` route not exposed (agent loop calls `RagIndex.search`
  as a service API; Phase 4/5 may add a debug route).
- Token approximation in repo-map + RAG retrieval is still `len // 4`;
  real tokenizer lands when Phase 4's agent loop needs it.
- No cross-process job persistence — server restart loses job state
  but indexed data survives in sqlite-vec.
- TypeScript / Go / Rust chunking still deferred.
