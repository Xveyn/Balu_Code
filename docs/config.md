# Balu Code Configuration Reference

Three configuration layers, applied in order (later overrides earlier):

1. **Server defaults** — `BaluCodePluginConfig` defaults in `plugin/config.py`
2. **Persisted server config** — edited via the web UI Config tab or `PUT /config`
3. **Project-local** — `.balucode.yaml` at the project root

---

## Server config (`BaluCodePluginConfig`)

Editable in the web UI under **Balu Code → Config** or via `PUT /api/plugins/balu_code/config`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ollama_base_url` | string | `http://127.0.0.1:11434` | Ollama API base URL |
| `chat_model` | string | `qwen2.5-coder:14b-instruct-q4_K_M` | Model used for agent turns |
| `embed_model` | string | `nomic-embed-text` | Model used for RAG embeddings |
| `context_window` | int | `32768` | Token context window sent to Ollama |
| `repo_map_budget` | int | `6144` | Max tokens reserved for the repo map |
| `rag_budget` | int | `4096` | Max tokens reserved for RAG chunks |
| `rag_top_k` | int | `8` | Number of RAG chunks retrieved per turn |
| `max_iterations` | int | `12` | Max agent loop iterations per turn |
| `max_total_tokens_per_turn` | int | `80000` | Hard token cap across all iterations |
| `temperature` | float | `0.2` | Sampling temperature (0.0–2.0) |

---

## CLI config (`~/.config/balu-code/config.yaml`)

Managed via `balu-code config get/set`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `server_url` | string | `""` | BaluHost server URL |
| `default_project_id` | int \| null | `null` | Project used when no `PROJECT_ID` given |

---

## Project config (`.balucode.yaml`)

Place at the project root. All fields are optional.

```yaml
model: qwen2.5-coder:7b        # override chat_model for this project
temperature: 0.3               # override temperature
context_window: 16384          # override context_window
max_iterations: 8              # override max_iterations

auto_approve:                  # tools to auto-approve without prompting
  - read_file
  - glob
  - grep
  - repo_map

deny:                          # tools to always deny (overrides auto_approve)
  - run_bash
```

### Tool names

| Tool | Risk | Description |
|------|------|-------------|
| `read_file` | read | Read a file's contents |
| `glob` | read | List files matching a pattern |
| `grep` | read | Search file contents |
| `repo_map` | read | Get the repository structure map |
| `write_file` | write | Create or overwrite a file |
| `apply_patch` | write | Apply a unified diff |
| `run_bash` | exec | Run a shell command |
| `web_fetch` | network | Fetch a URL |
