# Balu Code CLI Reference

Install: `pip install balu-code-cli`

## Global options

| Flag | Description |
|------|-------------|
| `--server URL` | Override the server URL from config |
| `--key KEY` | Override the API key from credentials store |

---

## auth

### `balu-code auth login`

Authenticate against a BaluHost server and store the API key.

```bash
balu-code auth login --server https://mynas.local --key balu_xxxxxxxxxxxx
```

### `balu-code auth status`

Show the currently configured server and whether the key is valid.

```bash
balu-code auth status
```

---

## init

Initialise the current directory as a Balu Code project and register it on the server.

```bash
balu-code init [--name NAME] [--path PATH]
```

If `--path` is omitted, the current working directory is used. Creates `.balucode.yaml` if absent.

---

## models

List all Ollama models available on the server.

```bash
balu-code models
```

---

## index

Start a background index job for a project.

```bash
balu-code index [PROJECT_ID]
```

If `PROJECT_ID` is omitted, uses the default project from config. Streams progress until done.

---

## chat

Open an interactive chat REPL with the coding agent.

```bash
balu-code chat [PROJECT_ID] [--yolo] [--model MODEL]
```

| Option | Description |
|--------|-------------|
| `--yolo` | Auto-approve all tool calls without prompting |
| `--model` | Override the chat model for this session |

### Approval flow

When the agent requests a tool call with `risk != "read"`, the CLI pauses and prompts:

```
[APPROVAL] write_file /home/user/src/foo.py
Allow? [y]es / [n]o / [Y]es-all / [N]o-all:
```

Priority order (first match wins):

1. `--yolo` flag → always approve
2. `.balucode.yaml` `auto_approve` list → approve if tool is listed
3. Stored permissions (`balu-code config set`) → approve or deny
4. Interactive prompt → `y`/`n` for once, `Y`/`N` for all of session

---

## session

Manage saved chat sessions. Sessions are stored as JSONL in `~/.local/share/balu-code/sessions/`.

### `balu-code session list`

```bash
balu-code session list
```

### `balu-code session resume SESSION_ID`

Replay a previous session in the terminal (server starts fresh — replay is display-only).

```bash
balu-code session resume abc123
```

### `balu-code session delete SESSION_ID`

```bash
balu-code session delete abc123
```

---

## config

Get or set CLI configuration values stored in `~/.config/balu-code/config.yaml`.

### `balu-code config get KEY`

```bash
balu-code config get server_url
```

### `balu-code config set KEY VALUE`

```bash
balu-code config set default_project_id 3
```

Available keys: `server_url`, `default_project_id`.
