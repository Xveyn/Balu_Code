# Phase A — Opencode Runtime Live Verification

End-to-end walkthrough for verifying the embedded opencode runtime on a live
BaluHost install. All commands run on the BaluHost host (no UI needed for
v0.2.0 — chat is API-only; a browser chat tab is tracked as a v0.3.0
enhancement).

## Prerequisites

- BaluHost backend running (`systemctl status baluhost-backend`)
- Ollama reachable at `http://127.0.0.1:11434`
- A model pulled that matches `BaluCodePluginConfig.chat_model` (default
  `qwen2.5-coder:14b` — verify with `curl -s http://127.0.0.1:11434/api/tags`)
- Worktree symlinked into BaluHost's plugin search path, e.g.
  `/opt/baluhost/backend/app/plugins/installed/balu_code → /home/sven/Balu_Code-opencode/plugin`

## Boot smoke

```bash
# 1. Restart backend so the symlinked plugin is picked up
sudo systemctl restart baluhost-backend
sleep 25  # allow first-run binary download (~50 MB → 150 MB extracted)

# 2. opencode subprocess healthy?
curl -sf http://127.0.0.1:4096/global/health
# → {"healthy":true,"version":"1.14.50"}

# 3. Plugin's view of the runtime
curl -sf http://127.0.0.1:8000/api/plugins/balu_code/runtime/status | python3 -m json.tool
# → { "healthy": true, "port": 4096, "pid": <int>, "binary_version": "1.14.50" }

# 4. opencode data dir was populated
ls ~/.local/share/balu-code/
# → opencode.json   opencode.log   runtime/   runtime.lock   store.db   ...

# 5. Generated opencode.json has the ollama provider wired up
cat ~/.local/share/balu-code/opencode.json
# → expect "provider.ollama.npm": "ollama-ai-provider-v2"
#   "provider.ollama.options.baseURL": "http://127.0.0.1:11434/api"
#   "provider.ollama.models" contains the chat_model

# 6. opencode sees the ollama provider + model
BIN=~/.local/share/balu-code/runtime/opencode-linux-x86_64
OPENCODE_CONFIG_DIR=~/.local/share/balu-code $BIN models ollama
# → ollama/<chat_model>
```

Any failure here means the runtime is not bootstrapping. Check
`~/.local/share/balu-code/opencode.log` and the latest log under
`~/.local/share/opencode/log/`.

## Chat round-trip

Replace `<PID>` with an existing balu_code project id (default `1` if you
followed the original v0.1.0 install). Create one via the existing
`POST /api/plugins/balu_code/projects` route (Bearer JWT required —
out of scope here) or pick one from the project store:

```bash
sqlite3 ~/.local/share/balu-code/store.db \
  "SELECT id, name, root_path FROM projects ORDER BY id;"
```

Send a prompt:

```bash
PID=1
time curl -s -X POST -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/plugins/balu_code/chat/v2/$PID \
  -d '{"messages":[{"role":"user","content":"Antworte mit genau einem Wort: hi"}]}' \
  | python3 -m json.tool | head -60
```

Expected:

- **Status 200**
- Response body: `{ "info": { ... "modelID": "<chat_model>", "providerID": "ollama" ... }, "parts": [ ... ] }`
- `info.providerID == "ollama"` and `info.modelID == "<your chat_model>"`
- `parts[]` contains at least a `step-start` part and a `text`/`reasoning` part with the assistant reply
- First call: ~10–30 s (Ollama loads the model). Subsequent: < 2 s.

If the response is `500 Internal Server Error`, fetch the traceback:

```bash
sudo journalctl -u baluhost-backend --since "30s ago" --no-pager 2>&1 \
  | grep -E 'Exception|Error|Traceback|httpx|chat_v2|opencode' | tail -40
```

The most common cause is a misconfigured provider (`provider.ollama.npm`,
`models`, or `baseURL` shape) — opencode returns `Provider not found:
ollama` or a 500 with `UnknownError` in that case. Compare your generated
`opencode.json` against `to_opencode_config()` in
`plugin/services/opencode_config.py`.

## Cancel

```bash
PID=1
curl -s -X POST http://127.0.0.1:8000/api/plugins/balu_code/chat/v2/$PID/cancel
# → {"status": "aborted"}
```

This is a no-op if no turn is in flight; opencode's abort endpoint is
idempotent.

## Multi-worker coordination check

With `--workers 4` in the systemd unit:

```bash
echo "Health probe distribution across 16 requests:"
declare -A c
for i in $(seq 1 16); do
  s=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/plugins/balu_code/runtime/status)
  c[$s]=$((${c[$s]:-0}+1))
done
for k in "${!c[@]}"; do echo "  $k: ${c[$k]}"; done
```

All 16 should be `200`. Anything else means workers diverged on plugin
enable — re-run `sudo systemctl restart baluhost-backend` and try again.

Verify only **one** worker holds the spawn lock:

```bash
lsof ~/.local/share/balu-code/runtime.lock
# Exactly one process should appear with `23uW REG`
```

The other three workers run as *attached* — they reuse the running
opencode server and never spawn their own.

## Crash recovery

```bash
# Kill the spawning worker's opencode child
pkill -f 'opencode-linux-x86_64'

# Wait up to 30 s — the watchdog should detect and restart
sleep 30
curl -sf http://127.0.0.1:4096/global/health && echo OK
```

If it stays down past the watchdog window (3 restarts within 5 min), the
plugin enters a degraded state. The `/runtime/status` endpoint will
return `healthy: false` and chat requests will 500/503.

## Tear-down (return to v0.1.0 main branch)

```bash
# Point the BaluHost-internal symlink back at the main checkout
ln -sfn /home/sven/projects/plugins/Balu_Code/plugin \
  /opt/baluhost/backend/app/plugins/installed/balu_code
sudo systemctl restart baluhost-backend

# Optional: clean up the worktree
git worktree remove --force /home/sven/Balu_Code-opencode
git branch -d feat/opencode-runtime
```

## Out of scope for this checklist

- Per-project CWD switching (currently opencode binds to BaluHost's
  systemd `WorkingDirectory` for the lifetime of the subprocess).
- SSE token streaming.
- A browser-side chat UI in `plugin/ui/bundle.js`.

All three are tracked as v0.3.0 candidates.

## TODO: opencode server password

opencode logs `Warning: OPENCODE_SERVER_PASSWORD is not set; server is
unsecured.` on every start. While the server only binds to `127.0.0.1`
in our setup, two situations escalate this from cosmetic to a real
security issue:

1. **Web UI exposure**: opencode's HTTP server already ships a full
   browser UI at `GET http://127.0.0.1:4096/`. Anyone with shell access
   to the host (any local user, any process) can drive the agent —
   read files, run shell commands under the plugin's uid — without auth.
2. **LAN exposure**: the moment the server binds to `0.0.0.0` (via
   `--hostname 0.0.0.0` or `--mdns`), every device on the LAN can
   reach the unauthenticated agent.

Fix (v0.3.0 candidate):
- Generate a random password at first plugin start, store it under
  `~/.local/share/balu-code/runtime.password` (mode 0600).
- Pass it as the `OPENCODE_SERVER_PASSWORD` env var when spawning
  opencode (see `start_or_attach_server` in `plugin/services/opencode_runtime.py`).
- Forward the same value in the `Authorization: Bearer <password>`
  header from `OpencodeClient` (so the existing `/chat/v2` path still
  works).
- Optional: surface the password in the BaluHost Runtime tab so admins
  can copy it for the standalone `opencode` CLI / browser usage
  (`OPENCODE_SERVER_PASSWORD=... opencode attach http://127.0.0.1:4096`).
