# Changelog

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
