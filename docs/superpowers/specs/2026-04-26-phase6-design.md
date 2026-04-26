# Balu Code Phase 6 — UI Bundle, Docs, Release

**Status:** Spec  
**Date:** 2026-04-26  
**Scope:** Ship the web settings panel (4-tab React bundle), user-facing documentation, release script, TestPyPI publish workflow, and marketplace submission guide.

## Context

Phases 1–5b are complete and on `main`. The plugin is functional via the CLI. Phase 6 makes it installable by anyone: a web UI inside BaluHost, docs for setup and operation, and an automated release pipeline.

## What is NOT in scope (Phase 6)

- **Chat in the web UI** — WebSocket streaming, approval dialogs, and message rendering in the browser are deferred to Phase 6b/v1.1. The CLI is the primary chat interface for v1.
- **Textual TUI** (already deferred in Phase 5c).
- **Version bump beyond 0.1.0** — first published version stays at 0.1.0.

## 1. UI Bundle

### Approach

Single monolithic `plugin/ui/bundle.js` (~350 lines). No build step. Uses `window.React` from the BaluHost host app, Tailwind utility classes matching the dark theme of `storage_analytics`. Pattern is identical to the existing `storage_analytics` plugin bundle.

### New backend endpoints

Three new endpoints added to `plugin/routes.py`:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/config` | Returns current `BaluCodePluginConfig` as JSON |
| `PUT` | `/config` | Accepts partial update dict, validates via Pydantic, persists via BaluHost plugin config mechanism |
| `GET` | `/logs?limit=100` | Queries `audit_logs` WHERE `event_type='BALU_CODE'` ORDER BY timestamp DESC, returns list |

### Tabs

| Tab | Content |
|-----|---------|
| **Models** | Calls `GET /models`. Lists all available Ollama models. Highlights current `chat_model` and `embed_model` from config. Read-only. |
| **Projects** | Calls `GET /projects`. Lists projects with name, path, indexed status. Create (name + path form), delete, trigger index job (`POST /index/{id}`), poll status (`GET /index/{id}/status`). |
| **Config** | Calls `GET /config` on mount. Renders a form for all `BaluCodePluginConfig` fields with their types and current values. Save button calls `PUT /config`. Shows success/error feedback. |
| **Logs** | Calls `GET /logs`. Renders a table: timestamp / user / action / resource / success. Last 100 entries, newest first. |

### Registration

`plugin/plugin.json` already has `"ui": {"bundle": "ui/bundle.js"}`. The `get_ui_manifest()` method in `plugin/__init__.py` must return a `PluginUIManifest` with a `nav_items` entry so the plugin appears in the BaluHost sidebar.

## 2. Documentation

Three files under `docs/`:

### `docs/install.md`

Server-side setup guide. Structure:
- **Requirements** — generic: BaluHost ≥ 1.30.0, Ollama ≥ 0.3, Python ≥ 3.11, GPU with ≥ 16 GB VRAM and ROCm ≥ 6.1 or CUDA ≥ 12.1. RX 7900 XT (20 GB ROCm) used as the concrete reference example throughout.
- **Ollama setup** — install, start, pull the two default models (`qwen2.5-coder:14b-instruct-q4_K_M`, `nomic-embed-text`)
- **Plugin installation** — download `.bhplugin` ZIP from GitHub Releases, upload via BaluHost → Plugins → Install
- **Smoke test** — `curl -H "Authorization: Bearer <key>" https://<host>/api/plugins/balu_code/health`

### `docs/cli.md`

CLI reference. One section per command group: `auth`, `init`, `models`, `index`, `chat`, `session`, `config`. For each: synopsis, options table, example invocation. Includes a dedicated section on the approval flow (priority: `--yolo` > `.balucode.yaml` > stored permissions > interactive `y/n/Y/N`).

### `docs/config.md`

Configuration reference. Three sections:
1. **`.balucode.yaml`** — project-local overrides, all fields with types, defaults, and description
2. **Server config (`BaluCodePluginConfig`)** — Ollama URL, model names, context window, budgets, iteration limits, temperature
3. **CLI config (`~/.config/balu-code/config.yaml`)** — AppConfig fields (server URL, API key path, default project)

## 3. Release Script

### `scripts/release.py`

Run locally: `python -m scripts.release [--version 0.1.0]`

Steps:
1. Read current version from `plugin/plugin.json` and `cli/pyproject.toml`; validate they match
2. Write new version string to both files
3. `git add plugin/plugin.json cli/pyproject.toml`
4. `git commit -m "chore(release): v{version}"`
5. `git tag v{version}`
6. `git push origin main --tags`

Fails fast if working tree is dirty before step 3 (except the two version files).

### `docs/CHANGELOG.md`

Hand-maintained. Initial content: `## v0.1.0` with a short summary of what shipped. The release script reads this file as the GitHub Release notes body but does not modify it — the developer updates it before running the script.

## 4. CI Additions

Two new jobs appended to `.github/workflows/ci.yml`, both gated on `startsWith(github.ref, 'refs/tags/v')` and `needs: test`.

### `release` job

1. Checkout + set up Python
2. `python -m scripts.build_bhplugin --repo-root . --dist dist/`
3. `python -m scripts.build_wheel --repo-root . --dist dist/`
4. `gh release create ${{ github.ref_name }} --title "Balu Code ${{ github.ref_name }}" --notes-file docs/CHANGELOG.md dist/*.bhplugin dist/*.whl`

Requires `GITHUB_TOKEN` (automatically available in Actions).

### `publish-cli` job

Runs after `release`. Uploads the CLI wheel to TestPyPI:

1. Build wheel (same script)
2. `pip install twine`
3. `twine upload --repository testpypi dist/*.whl`

Requires `TEST_PYPI_TOKEN` secret in the repo. To switch to production PyPI later: change `testpypi` → `pypi`, rename the secret.

## 5. Marketplace Submission

No automation. `docs/marketplace-submission.md` documents the three manual steps:
1. Fork `Xveyn/BaluHost-Plugin-Market`
2. Add entry to `plugins/index.json` (fields: name, display_name, version, description, author, category, homepage, min_baluhost_version, bundle_url pointing to the GitHub Release asset)
3. Open a PR

This is a one-time action after the first successful release.

## Deliverables Summary

| File | Status |
|------|--------|
| `plugin/ui/bundle.js` | new |
| `plugin/routes.py` | +3 endpoints (GET/PUT /config, GET /logs) |
| `plugin/__init__.py` | +nav_items in get_ui_manifest() |
| `docs/install.md` | new |
| `docs/cli.md` | new |
| `docs/config.md` | new |
| `docs/CHANGELOG.md` | new |
| `docs/marketplace-submission.md` | new |
| `scripts/release.py` | new |
| `.github/workflows/ci.yml` | +release and publish-cli jobs |
