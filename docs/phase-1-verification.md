# Phase 1 verification — 2026-04-18

## Environment (local dev)

- Commit: `33f2216` (Phase 1 complete, pre-verification)
- Python: 3.13.5 (local venv; CI matrix covers 3.11 & 3.12)
- OS: Debian 13 (Linux 6.12), bash
- GPU/CPU: RX 7900 XT (ROCm) — not exercised in Phase 1

## Automated checks (run locally before merge)

- [x] `ruff check .` — no findings
- [x] `ruff format --check .` — 21 files already formatted
- [x] `pytest -v` — **34 passed** across 4 test directories:
  - `shared/tests/test_events.py` — 14
  - `plugin/tests/test_metadata.py` — 5
  - `plugin/tests/test_health_route.py` — 2
  - `cli/tests/test_version.py` — 3
  - `scripts/tests/test_build_bhplugin.py` — 6
  - `scripts/tests/test_build_wheel.py` — 4
- [x] `python -m scripts.build_bhplugin --repo-root . --dist dist/` produces
      `dist/balu_code-0.1.0.bhplugin` + `.sha256` sidecar
- [x] `python -m scripts.build_wheel --repo-root . --dist dist/` produces
      `dist/balu_code_cli-0.1.0-py3-none-any.whl` and cleans up `cli/src/balu_code_cli/_vendored/`
- [x] `balu-code --version` → `balu-code 0.1.0`
- [ ] GitHub Actions: CI green on `main` (fill in run URL after first push)

## Manual checks to run against dev BaluHost

Phase 1 can't be fully verified from the Balu_Code repo alone — it also needs
to actually load inside a running BaluHost backend. These steps are executed
by the maintainer on the BaluHost host:

- [ ] Extract `dist/balu_code-0.1.0.bhplugin` into
      `/opt/baluhost/backend/app/plugins/installed/balu_code/`
- [ ] `pip install -r app/plugins/installed/balu_code/requirements.txt` into
      BaluHost's venv (expects httpx + pydantic, already present)
- [ ] Restart `baluhost-backend`
- [ ] Enable plugin via admin UI or the SQL insert in the Phase 1 plan
- [ ] `GET /api/plugins/balu_code/health` → `{"status":"ok","plugin":"balu_code","version":"0.1.0"}`

## Plan deviations

Two small divergences from the original plan, both committed with explanatory
messages:

1. **Added repo-root `conftest.py`** that inserts the BaluHost stub onto
   `sys.path` before test collection. The plan's `plugin/tests/conftest.py`
   alone is not enough because `plugin/tests/__init__.py` makes
   `plugin.tests` a subpackage — pytest imports `plugin/__init__.py` (which
   itself imports `app.plugins.base`) before `conftest.py` runs.

2. **Switched pytest to `--import-mode=importlib`** and added `scripts/tests`
   to `testpaths`. Without importlib mode, `plugin/tests`, `cli/tests`, and
   `scripts/tests` collide on the bare `tests` module name. Using importlib
   also means `cli/tests/__init__.py` is no longer strictly necessary, but
   it was kept to match the plan.

3. **Fixed a bug in the plan's `test_event_union_includes_all_six`**:
   `typing.get_args` on `Annotated[Union[...], Field(...)]` returns
   `(Union[...], FieldInfo)`, not the five envelope classes. The test was
   renamed to `test_event_union_includes_all_five` and now unwraps both
   layers. Also, only five envelopes exist (UserMessage, TurnStart, Token,
   TurnEnd, Error) — "six" in the plan appears to be a miscount.

## Known issues carried into Phase 2

- Live BaluHost sideload verification deferred until the dev BaluHost host is
  available. No code issue expected; it's purely a deployment dry-run.
