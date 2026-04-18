# Phase 3a verification — 2026-04-18

## Environment (local dev)

- Commit: `60ea4e4`
- Python: 3.13.5 (CI matrix covers 3.11 & 3.12)

## Automated checks

- [x] `ruff check .` — clean
- [x] `ruff format --check .` — clean (45 files already formatted)
- [x] `pytest -v` — `137` tests passing
- [x] `python -m scripts.build_bhplugin` includes
      `routes.py`, `schemas.py`, `services/repo_map.py`,
      `services/repo_map_python.py`, `services/repo_map_types.py`,
      plus the Phase-2 modules (`services/ollama_client.py`,
      `services/project_store.py`, `balu_code_shared/events.py`)
      — **22 files total** in the archive
- [x] `python -m scripts.build_wheel` still produces the CLI wheel
- [ ] GitHub Actions: CI green on `main` (fill in after push)

## dist/ artefacts

```
balu_code-0.1.0.bhplugin
balu_code-0.1.0.bhplugin.sha256
balu_code_cli-0.1.0-py3-none-any.whl
```

## Manual checks against dev BaluHost

- [ ] Re-sideload the new `.bhplugin` into
      `/opt/baluhost/backend/app/plugins/installed/balu_code/`
- [ ] BaluHost venv installs `tree-sitter` and `tree-sitter-python`
      (from the new `python_requirements`)
- [ ] Restart the BaluHost backend
- [ ] `GET /api/plugins/balu_code/projects/{id}/repo_map` against a
      registered Python project returns `text` + `file_count > 0`
- [ ] `?budget=512` truncates as expected

## Plan deviations

Commits in `a7bad2c..60ea4e4` that were not the primary task `feat:`:

- `2eadcea` — `docs: add Phase 3a implementation plan` (pre-task scaffolding)
- `36d68c5` — `refactor(plugin): extract Pydantic schemas to plugin/schemas.py`
  — schemas were originally inline in routes; extracted to avoid a circular
  import discovered during Task 5.
- `2f2cb83` — `refactor(plugin): extract router factory to plugin/routes.py`
  — same circular-import root cause; router now lives in its own module.
- `1229627` — `refactor(plugin): tighten parse_python_file thread safety + naming`
  — opportunistic cleanup of the tree-sitter parser after review; the function
  was not thread-safe due to a shared parser instance.
- `1b48dc5` — `refactor(plugin): break repo_map circular import + drop dead code`
  — introduced `services/repo_map_types.py` to hold shared dataclasses so
  `repo_map.py` and `repo_map_python.py` could import each other without a cycle.
- `948b6f2` — `feat(plugin): add RepoMap.walk_and_cache (mtime + sha1 incremental cache)`
  — Task 6; the walker was rewritten to use SHA-1 as the primary invalidation
  key (mtime first for speed, SHA-1 to confirm) after the original mtime-only
  approach proved unreliable across filesystem boundaries.
- `60ea4e4` — `fix(plugin): use HTTP_422_UNPROCESSABLE_CONTENT (silence Starlette deprecation)`
  — Starlette 0.46 deprecated the old constant; swapped to the new one to keep
  test output clean.

## Known issues carried into Phase 3b

- Repo-map only covers Python; TypeScript/Go are deferred.
- Token approximation is `len(text) // 4`; real tokenizer lands when
  the agent loop ships in Phase 4.
- Smart ranker (recently-edited / import-weight / opened-in-chat) is
  still TODO; alphabetical sort for now.
- Walks happen synchronously inside the request handler. First call on
  a large repo is slow; subsequent calls are cache-fast. Background
  job machinery comes with `POST /projects/{id}/index` in Phase 3b.
