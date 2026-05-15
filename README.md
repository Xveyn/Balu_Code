# Balu Code

Self-hosted coding agent for [BaluHost](https://github.com/Xveyn/Baluhost). Powered by [opencode](https://github.com/sst/opencode), controlled via the BaluHost web UI or the embedded opencode CLI.

**Current version:** 0.2.0

## Architecture

Balu_Code wraps a vendored [opencode](https://github.com/sst/opencode) binary as the coding agent runtime. The plugin manages BaluHost integration (auth, audit, config UI, project storage) while opencode owns the agent loop, tools, prompts, and LLM calls. The opencode binary is downloaded on first plugin start (~50 MB) and verified against a pinned sha256.

## Features

**Agent** (via opencode)
- Streaming chat REPL with agentic tool loop
- Per-tool approval gate: `--yolo` / `.balucode.yaml` / stored permissions / interactive prompt
- Tools: full opencode tool suite (code read/write, bash, web fetch, etc.)
- Semantic repo understanding + RAG
- Audit log written to BaluHost `audit_logs` table

**Plugin (web UI)**
- Models, Projects, Config, Logs, System, Stats tabs
- Live session management via WebSocket
- System tab: live VRAM bar, loaded models, GPU utilisation (polled every 3–30 s)
- Stats tab: 7/14/30/90-day usage dashboard (requests, tokens, models, tools, approvals) + live active-turn banner

**CLI** (via embedded opencode)
- Interactive chat REPL with agentic approval flow
- One-shot prompts with `opencode-linux-x86_64 run "..."`
- Full opencode command suite (models, config, etc.)
- See [`docs/cli.md`](docs/cli.md) for usage

## Requirements

| Component | Version |
|-----------|---------|
| BaluHost | ≥ 1.29.0 |
| Ollama | 0.3.x (on `127.0.0.1:11434`) |
| GPU VRAM | Depends on opencode config + selected LLM model |
| GPU driver | ROCm ≥ 6.1 or CUDA ≥ 12.1 |

**Reference hardware:** AMD RX 7900 XT (20 GB GDDR6, ROCm 6.2).

**Note:** The opencode binary is self-contained; no separate system Bun or Node.js installation required.

## Quick Start

```bash
# 1. Install the plugin
# Download balu_code-0.2.0.bhplugin from GitHub Releases,
# then upload via BaluHost → Plugins → Install plugin.

# 2. Use the web UI to configure models and create projects.

# 3. Start chatting via the web UI, or use the embedded opencode binary:
~/.local/share/balu-code/runtime/opencode-linux-x86_64
```

See [`docs/install.md`](docs/install.md) for the full installation guide including ROCm setup.

## Repository Layout

| Dir | Purpose | Distribution |
|-----|---------|--------------|
| `plugin/` | BaluHost server plugin (`balu_code`) | `.bhplugin` ZIP → BaluHost Plugin Marketplace |
| `shared/` | Pydantic event schemas, common types | path-dep in dev, vendored on build |
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
- [`docs/remote-client.md`](docs/remote-client.md) — run opencode on a client laptop against the BaluHost server
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) — release history

## License

MIT — see [`LICENSE`](LICENSE).
