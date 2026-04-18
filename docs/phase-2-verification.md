# Phase 2 verification — 2026-04-18

## Environment (local dev)

- Commit: `390751e`
- Python: 3.13.5 (local venv; CI matrix covers 3.11 & 3.12)

## Automated checks

- [x] `ruff check .` — no findings
- [x] `ruff format --check .` — clean (one file reformatted before this commit:
      `plugin/tests/test_routes_phase2.py` — chained assert was unwrapped by ruff)
- [x] `pytest -v` — 87 tests passing
- [x] `python -m scripts.build_bhplugin` produces an archive that includes
      `config.py`, `data_dir.py`, `deps.py`, `services/ollama_client.py`,
      `services/project_store.py`, plus the vendored `balu_code_shared/` tree
- [x] `python -m scripts.build_wheel` still produces the CLI wheel
- [ ] GitHub Actions: CI green on `main` (fill in run URL after push)

## dist/ artefacts

```
balu_code-0.1.0.bhplugin
balu_code-0.1.0.bhplugin.sha256
balu_code_cli-0.1.0-py3-none-any.whl
```

`.bhplugin` contains 17 files:

```
__init__.py
balu_code_plugin_dev.egg-info/PKG-INFO
balu_code_plugin_dev.egg-info/SOURCES.txt
balu_code_plugin_dev.egg-info/dependency_links.txt
balu_code_plugin_dev.egg-info/requires.txt
balu_code_plugin_dev.egg-info/top_level.txt
balu_code_shared/__init__.py
balu_code_shared/events.py
balu_code_shared/py.typed
config.py
data_dir.py
deps.py
plugin.json
requirements.txt
services/__init__.py
services/ollama_client.py
services/project_store.py
```

## Manual checks to run against dev BaluHost

- [ ] Re-sideload the new `.bhplugin` into
      `/opt/baluhost/backend/app/plugins/installed/balu_code/`
- [ ] Restart the BaluHost backend
- [ ] Check the startup log: plugin reports the `resolve_data_dir()` path and
      the ProjectStore opens without errors
- [ ] `GET /api/plugins/balu_code/health` — still 200 ok
- [ ] `POST /api/plugins/balu_code/projects` with `{name: "demo", root_path: "/tmp", config_yaml: null}` → 201
- [ ] `GET /api/plugins/balu_code/projects` → contains "demo"
- [ ] `GET /api/plugins/balu_code/models` → lists whatever Ollama has pulled

## Plan deviations

Based on `git log --oneline b6012e8..HEAD` (Phase 2 route tasks) and the
broader Phase 2 log, several unplanned follow-up commits were needed:

- `40d0d8b style(plugin): drop unused Path import in test_data_dir` — ruff
  flagged an unused import added during Phase 2 task 7; removed in a separate
  style commit rather than squashing.
- `f66b62c refactor(plugin): clarify OllamaClient retry count + add 429/timeout
  tests` — the code-quality reviewer requested that the retry sentinel (`-1` as
  "exhausted") be made explicit and that 429 + timeout paths get dedicated test
  coverage; added as a separate refactor commit.
- `6087de8 refactor(plugin): chat_stream error-path tests + type annotation` —
  reviewer flagged missing error-path coverage and an unannotated return type on
  `chat_stream`; fixed as a separate commit.
- `df87199 refactor(plugin): tighten ProjectStore lock + use sqlite_errorname` —
  reviewer noted that the lock scope in ProjectStore was narrower than necessary
  and that the raw `sqlite3.IntegrityError` check should use `sqlite_errorname`
  for correctness; addressed in a dedicated refactor.
- `b6012e8 refactor(plugin): harden lifecycle + move singleton-reset fixture to
  conftest` — after wiring the lifecycle the singleton-reset fixture was
  duplicated across test files; consolidated into `conftest.py` and lifecycle
  guard-rails were hardened.
- `485d0a9 chore: allowlist FastAPI Depends etc. for ruff B008 instead of
  per-line noqa` — ruff `B008` (function-call in default) flagged FastAPI
  `Depends(...)` expressions in route signatures; solved globally via
  `pyproject.toml` extend-ignore rather than sprinkling per-line `# noqa`.
- `a756d50 style: apply ruff format auto-fixes (blank line after module
  docstring, unwrap short calls)` — bulk ruff format pass after the routes were
  written; two style nits (missing blank line, over-wrapped one-liner) fixed
  automatically.
- `390751e style: apply ruff format fix in test_routes_phase2 (chained assert)` —
  ruff reformatted the chained `assert c.post(...).status_code == 401` into the
  parenthesised form required by the line-length limit; fixed just before this
  verification commit.

## Known issues carried into Phase 3

- `repo_map_cache` table is created but empty until Phase 3 lands the walker.
- `chat_stream` is implemented but has no in-process caller yet; the agent
  loop lands in Phase 4.
- Live `OllamaClient` errors against a real Ollama instance are not exercised
  in the test suite; `MockTransport` covers the parser + retry logic.
