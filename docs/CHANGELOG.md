# Changelog

## Unreleased

### Changed
- **Breaking:** the plugin's own config endpoints moved from `/config` to
  `/settings` (`GET`/`PUT /api/plugins/balu_code/settings`). BaluHost registers
  `/api/plugins/{name}/config` before plugin routers are mounted, so the plugin's
  route never received a request — the core route answered, stored the value in
  BaluHost's database and never handed it to the plugin. Symptoms: the Config tab
  showed empty fields (it parsed the core `{name, config, schema}` shape) and
  saving failed with 422 `body.config Field required`.

### Fixed
- Plugin UI rendered a blank page: the bundle still used the pre-sandbox host
  contract (`window.React`, `localStorage` token, direct `fetch`) and died on
  load with "React is undefined". BaluHost runs plugin UIs in an iframe with
  `sandbox="allow-scripts"` and no `allow-same-origin`, so all three are
  unavailable — React and hooks now come from `window.BaluHost`, and every
  request goes through its proxied api (own-plugin routes need no scope).
- Config tab could not save: it echoed the whole GET /config object back, but
  `ConfigUpdateRequest` is `extra="forbid"` and has no `opencode_port`, so the
  PUT was answered with 422. Only editable fields are sent now.
- Dropped the Index button and the active-turn banner — they called
  `/index/{id}` and `/turns/current`, removed back in 0.2.0.

### Added
- `scripts/deploy-local.sh` — build and install this checkout into a local
  BaluHost: backup, swap, restart, health check, and an automatic rollback
  when the plugin does not come back. Covers the gap that BaluHost has no
  upload route for local plugins. File ownership is derived from the systemd
  unit and validated before anything is stopped; any failure after the swap
  restores the previous directory and restarts the service, so a failed deploy
  never leaves the backend down.
- `think` config field: turns the reasoning trace of thinking-capable models
  (`qwen3.8` and friends) on or off, forwarded to opencode as
  `providerOptions.ollama.think`. Three-valued — unset omits the flag entirely,
  because a model without the capability can reject a request that carries it.
  On the reference box the same coding task cost 2493 output tokens / 65.8 s
  with the trace and 1096 / 27.7 s without.
- `docs/install.md`: qwen3.8:27b setup for a 20 GB card — Ollama env
  (`OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE=q8_0`), Modelfile for the
  sampling parameters, and how to verify the model actually fits.

### Fixed
- A config change made through `PUT /config` (or the web UI Config tab) now
  reaches the agent. `opencode.json` used to be written only during
  `on_startup()`, so a newly selected model was missing from
  `provider.ollama.models` and opencode kept answering with the old one — or
  lost its `num_ctx` and silently truncated its own system prompt against
  Ollama's 4096-token default. The route now rewrites the file and restarts the
  runtime, and reports via the `X-Balu-Code-Runtime-Restarted` response header
  when it could not (worker only attached to a sibling's process → restart the
  backend).
- `temperature` from the plugin config is now actually sent to Ollama. It was
  stored, validated and then dropped in the opencode config mapping.

### Ops
- Minimum Ollama version raised to 0.32.12 in the docs (was 0.3.x, which
  predates every model this plugin now recommends).

## 0.2.1 — 2026-05-15

### Added
- Remote-client workflow: run opencode locally on a laptop, proxy LLM calls
  to the BaluHost-hosted Ollama via a new authenticated route
  `GET/POST /api/plugins/balu_code/ollama/{path}`. Auth uses BaluHost API
  keys (`balu_…` Bearer tokens) — same dependency as the rest of the plugin,
  no new auth surface.
- `scripts/bootstrap-remote-client.sh` — downloads pinned opencode binary,
  verifies checksum, prompts for API key, renders client config.
- `docs/remote-client.md` — install + ops guide.

### Ops
- New nginx `location` block required to carve `/api/plugins/balu_code/ollama/`
  out of Basic Auth. Snippet at `docs/remote-client/nginx.example.conf`.

## 0.2.0 — 2026-05-14

### Changed
- **Replaced internal coding agent with embedded opencode runtime (v1.14.50).**
  The plugin no longer implements its own agent loop, tool registry, RAG
  index, or repo map. Instead it manages a vendored `opencode` standalone
  binary as a subprocess and proxies sessions to it. ~7,800 LOC removed.
- Chat endpoint changed from WebSocket `POST /chat` to synchronous JSON
  `POST /chat/v2/{project_id}`. SSE token streaming is a v0.3.0 candidate.
- Plugin config (Ollama URL, default model) is now translated to an
  `opencode.json` written under the plugin's data dir.

### Added
- New routes: `POST /chat/v2/{project_id}`, `POST /chat/v2/{project_id}/cancel`,
  `GET /runtime/status`, `POST /runtime/restart`.
- New UI tab `Runtime` showing opencode binary version, listening port, and
  worker-spawn ownership state.

### Removed
- Routes: `WebSocket /chat`, `GET /turns/current`, `GET /projects/{id}/repo_map`,
  `POST /projects/{id}/index`, `GET /projects/{id}/index/status/{job}`.
- Python deps: `tree-sitter*`, `tiktoken`, `sqlite-vec`, `trafilatura`, `unidiff`.

## v0.1.0 — 2026-04-26

First public release.

### Plugin
- FastAPI plugin for BaluHost with full agent loop (read + write tools + approval gate)
- Ollama integration with ROCm support (default: `qwen2.5-coder:14b-instruct-q4_K_M`)
- Tree-sitter repo map (Python support) + semantic RAG via `nomic-embed-text`
- Tool registry: `read_file`, `glob`, `grep`, `repo_map`, `write_file`, `apply_patch`, `run_bash`, `web_fetch`
- Per-tool approval gate: `--yolo` / `.balucode.yaml` / stored permissions / interactive
- Audit log integration (writes to BaluHost `audit_logs` table)
- WebSocket streaming chat endpoint
- Web settings panel: Models / Projects / Config / Logs tabs

### CLI
- `balu-code auth login/status` — authenticate against BaluHost
- `balu-code init` — register a project
- `balu-code models` — list available Ollama models
- `balu-code index` — start + stream an index job
- `balu-code chat` — interactive streaming chat REPL with approval flow
- `balu-code session list/resume/delete` — manage saved sessions
- `balu-code config get/set` — manage CLI configuration
