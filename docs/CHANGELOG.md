# Changelog

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
