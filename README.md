# Balu Code

Self-hosted coding agent for [BaluHost](https://github.com/Xveyn/Baluhost). Runs against a local Ollama instance, controlled via a terminal CLI or the BaluHost web UI.

**Current version:** v0.1.0

## Features

**Agent**
- Streaming chat REPL with agentic tool loop
- Per-tool approval gate: `--yolo` / `.balucode.yaml` / stored permissions / interactive prompt
- Tools: `read_file`, `glob`, `grep`, `repo_map`, `write_file`, `apply_patch`, `run_bash`, `web_fetch`
- Tree-sitter repo map (Python) + semantic RAG via `nomic-embed-text`
- Audit log written to BaluHost `audit_logs` table

**Plugin (web UI)**
- Models, Projects, Config, Logs tabs
- Live session management via WebSocket

**CLI**
- `balu-code auth login/status` — authenticate against BaluHost
- `balu-code init` — register a project
- `balu-code models` — list available Ollama models
- `balu-code index` — trigger and stream an index job
- `balu-code chat [--yolo] [--model]` — interactive streaming chat REPL
- `balu-code session list/resume/delete` — manage saved sessions
- `balu-code config get/set` — manage CLI configuration

## Requirements

| Component | Version |
|-----------|---------|
| BaluHost | ≥ 1.29.0 |
| Ollama | 0.3.x (on `127.0.0.1:11434`) |
| GPU VRAM | 16 GB (for `qwen2.5-coder:14b-instruct-q4_K_M` at q4) |
| GPU driver | ROCm ≥ 6.1 or CUDA ≥ 12.1 |

**Reference hardware:** AMD RX 7900 XT (20 GB GDDR6, ROCm 6.2).

## Quick Start

```bash
# 1. Pull the Ollama models
ollama pull qwen2.5-coder:14b-instruct-q4_K_M
ollama pull nomic-embed-text

# 2. Install the plugin
# Download balu_code-0.1.0.bhplugin from GitHub Releases,
# then upload via BaluHost → Plugins → Install plugin.

# 3. Install the CLI
pip install balu-code-cli
balu-code auth login --server https://<host> --key <key>

# 4. Register a project and start chatting
cd ~/my-project
balu-code init
balu-code index
balu-code chat
```

See [`docs/install.md`](docs/install.md) for the full installation guide including ROCm setup.

## Repository Layout

| Dir | Purpose | Distribution |
|-----|---------|--------------|
| `plugin/` | BaluHost server plugin (`balu_code`) | `.bhplugin` ZIP → BaluHost Plugin Marketplace |
| `cli/` | Terminal client (`balu-code`) | `balu-code-cli` wheel → PyPI |
| `shared/` | Pydantic event schemas shared by both | path-dep in dev, vendored on build |
| `scripts/` | Build and release tooling | — |
| `docs/` | Install guide, CLI reference, config reference | — |

## Configuration

Three layers applied in order (later overrides earlier):

1. Server defaults (`plugin/config.py`)
2. Persisted server config — web UI **Balu Code → Config** tab or `PUT /api/plugins/balu_code/config`
3. Project-local — `.balucode.yaml` at the project root

```yaml
# .balucode.yaml — all fields optional
model: qwen2.5-coder:7b
temperature: 0.3
auto_approve:
  - read_file
  - glob
  - grep
  - repo_map
deny:
  - run_bash
```

See [`docs/config.md`](docs/config.md) for the full configuration reference.

## Docs

- [`docs/install.md`](docs/install.md) — installation and Ollama setup
- [`docs/cli.md`](docs/cli.md) — CLI command reference
- [`docs/config.md`](docs/config.md) — configuration reference
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) — release history

## License

MIT — see [`LICENSE`](LICENSE).
