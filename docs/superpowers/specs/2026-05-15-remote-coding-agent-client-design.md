# Remote Coding Agent Client — Design

**Date:** 2026-05-15
**Author:** Sven (Xveyn) + Claude
**Status:** Approved by user, ready for implementation planning
**Scope:** Enable a Claude-Code-style workflow where opencode runs locally on a
client machine (laptop) and edits client-side files, while the LLM (Ollama on
GPU) runs on the BaluHost server. Auth uses BaluHost API keys.

## Why

Today the coding agent is reachable two ways: the BaluHost web UI (chat in a
browser tab) or by SSHing into the server and running the embedded opencode
binary. Both keep the working files on the *server*. Sven wants the CLI
ergonomics of Claude Code: terminal on the laptop, edits on the laptop, model
on the GPU server.

opencode itself does not implement a client-server-with-client-side-tools
protocol — its server executes tools in its own CWD. The pragmatic path is to
run opencode entirely on the client (single self-contained binary) and proxy
the LLM calls back to the server.

## Architectural decisions (fixed before this spec)

These were settled during brainstorming and are not reopened here:

1. **Where opencode runs:** locally on the client. Tools (read/write/bash)
   execute on the client filesystem.
2. **What is remote:** Ollama only. The BaluHost server is the LLM provider.
3. **Auth:** BaluHost API keys (Bearer tokens with `balu_` prefix). No new
   auth mechanism, no shared Basic Auth password.
4. **Where the proxy lives:** a new route inside the Balu_Code plugin, *not*
   in nginx. The plugin already sits behind `Depends(get_current_user)`, which
   accepts both JWT and API keys, so no auth code is duplicated.
5. **BaluHost integration depth:** none beyond auth in v1. Client-side sessions
   do not appear in the web UI session list, do not feed audit_log entries,
   do not share state with server-side sessions. (Audit hook is a follow-up.)
6. **Nginx change scope:** turn off Basic Auth for the single new route
   `/api/plugins/balu_code/ollama/*`. Everything else stays as it is.

## Architecture

```
Client laptop                            BaluHost server
─────────────                            ────────────────
~/projects/foo/                          nginx :8443
  ├─ src/...                              │  auth_basic off for /ollama/
  └─ ~/.config/opencode/                  ▼
       opencode.json                     FastAPI /api/plugins/balu_code/
                                          │  Depends(get_current_user)
opencode-linux-x86_64 (v1.14.50)          │  validates `balu_…` key
  │                                       ▼
  │  POST /api/.../ollama/api/chat       OllamaProxy route
  │  Authorization: Bearer balu_…         │  httpx.AsyncClient.stream()
  └─────────► HTTPS ─────────────────────►│
                                          ▼
                                         Ollama :11434
                                         (GPU, ROCm)
```

### Components

**Server-side (Balu_Code plugin):**

- `plugin/routes.py` — new endpoint family
  `ANY /ollama/{path:path}` (GET + POST). Path-passthrough, no per-endpoint
  enumeration. Stream request body forward, stream response body back.
- `plugin/services/ollama_proxy.py` (new) — thin async function that takes the
  incoming `Request` and a target base URL, opens an `httpx.AsyncClient.stream()`
  against `{base_url}/{path}`, and returns a FastAPI `StreamingResponse` that
  pipes the bytes through. Keeps the route file thin.
- `plugin/tests/test_routes_ollama_proxy.py` (new) — covers: auth gate (401
  without/with bad key), happy path proxy of a simple `/api/tags`-shaped
  response, streaming pass-through of a chunked response, upstream error
  propagation.

**Nginx (server):**

- One new `location` block:
  ```nginx
  location /api/plugins/balu_code/ollama/ {
      auth_basic off;
      proxy_pass http://127.0.0.1:8000;
      proxy_buffering off;
      proxy_read_timeout 600s;
      client_max_body_size 64m;
      # plus existing proxy_set_header lines
  }
  ```
- Documented in `docs/install.md` (or a new `docs/remote-client.md`).

**Client-side:**

- `docs/remote-client.md` (new) — install guide. Two paths:
  - **Bootstrap script** (recommended): `./scripts/bootstrap-remote-client.sh`
    handles download, checksum verify, key prompt, and config rendering.
  - **Manual**: download opencode v1.14.50 from upstream + SHA-256-verify,
    create an API key in BaluHost (User → API Keys → New), copy
    `docs/remote-client/opencode.json.tmpl` to `~/.config/opencode/opencode.json`,
    replace the four `__PLACEHOLDER__` tokens (`__BASE_URL__`, `__API_KEY__`,
    `__MODEL__`, `__NUM_CTX__`), `chmod 0600` the file, then `cd ~/projects/foo && opencode`.
- Template `docs/remote-client/opencode.json.tmpl` (rendered by the bootstrap
  script — placeholders are replaced before the file lands at
  `~/.config/opencode/opencode.json`):
  ```json
  {
    "$schema": "https://opencode.ai/config.json",
    "model": "ollama/__MODEL__",
    "provider": {
      "ollama": {
        "npm": "ollama-ai-provider-v2",
        "name": "BaluHost remote Ollama",
        "options": {
          "baseURL": "__BASE_URL__",
          "headers": { "Authorization": "Bearer __API_KEY__" }
        }
      }
    }
  }
  ```
  The provider block mirrors what `opencode_config.py` already writes
  server-side; only `baseURL` + `headers` differ.

### Data flow

A single chat turn from the client:

1. User types in client `opencode` REPL.
2. opencode resolves prompt → wants `POST /api/chat` on its configured Ollama
   provider.
3. ollama-ai-provider-v2 (AI SDK) calls
   `https://baluhost.example/api/plugins/balu_code/ollama/api/chat` with the
   `Authorization: Bearer balu_…` header from the provider's `headers` option
   (env-expanded from `BALU_API_KEY`).
4. nginx forwards (no Basic Auth for this path) to FastAPI.
5. FastAPI runs `get_current_user`:
   - Sees `balu_` prefix → validates against `api_keys` table.
   - Records usage (`last_used_at`, `last_used_ip`, `use_count`).
   - Yields `UserPublic`; request proceeds.
6. `ollama_proxy` opens streaming connection to `127.0.0.1:11434/api/chat`,
   forwards the raw request body, pipes the chunked response back.
7. opencode reads tokens, runs the agent loop *locally*; tool calls
   (read_file, write_file, bash) execute on the client filesystem.
8. On the next LLM round-trip, repeat from step 3.

### Error handling

- **Bad / missing API key:** 401 from `get_current_user`, surfaces in opencode
  as an HTTP error (provider sees status 401). Documented: regenerate key in
  web UI.
- **Ollama unreachable** (e.g. service down): proxy gets connection refused,
  returns 502. Pre-existing `OllamaUnreachable` handling on the plugin side is
  for the *web UI* path (`/system`, `/models`); we do not duplicate it here —
  the proxy is transport, not retry logic.
- **Streaming response interrupted:** httpx raises mid-stream, FastAPI's
  StreamingResponse propagates the abort, opencode treats it as a normal
  network failure (its own retry policy applies).
- **Body too large / timeout:** governed by the nginx limits set above
  (64 MiB body, 600 s read). Embeddings batches stay well below.

### Security properties (kept honest)

In place:
- TLS in transit (existing cert).
- API keys hashed at rest (SHA-256 over 180-bit token).
- Per-key revocation, expiry, usage trail (`use_count`, `last_used_ip`).
- Key scoped to `target_user_id` — cannot act as another user.
- Ollama remains bound to `127.0.0.1`; only the authenticated proxy reaches it.

Known limitations, accepted for v1:
- **Key scope is user-wide, not endpoint-scoped.** A leaked key can hit any
  BaluHost endpoint as that user, not just `/ollama/`. Mitigation if needed
  later: dedicated low-privilege user, keys against that user.
- **No rate limit per key.** A leaked key can hammer the GPU until revoked.
  Acceptable for a single-maintainer self-hosted setup.
- **Prompts/responses are not audit-logged** — only the fact of one
  authenticated API-key use. Matches BaluHost's existing audit policy.
- **TLS validation depends on the client trusting the BaluHost cert.** With
  Let's Encrypt or an internal CA already trusted on the laptop, no issue.
  Self-signed certs require `NODE_EXTRA_CA_CERTS` or similar.

## Out of scope (deliberate)

- Server-side audit_log entries per Ollama call — follow-up; design hook in
  `ollama_proxy.py` should make it a 5-line addition (read `request.state.
  api_key_id`, call `audit_log.record_*`).
- Per-key rate limiting — follow-up.
- Web UI surfacing of client-side sessions — follow-up if ever needed.
- Routing client-side opencode through the BaluHost-managed opencode server
  (proxying `/opencode/*` instead of `/ollama/*`) — was considered, rejected
  because opencode-server doesn't model client-side tool execution.
- A `balu-code`-branded CLI wrapper — opencode-CLI is the CLI per the 0.2.0
  decision.
- Supporting clients other than Linux x86_64 (opencode publishes macOS and
  Windows binaries too; the same config works, just different checksums to
  document).

## Testing

- **Unit / integration tests** (server-side, run in CI):
  - 401 without `Authorization` header.
  - 401 with malformed / expired / revoked key.
  - 200 happy path: client sends `GET /ollama/api/tags`, proxy returns the
    upstream body byte-for-byte.
  - Streaming pass-through: chunked response from a fake upstream arrives in
    chunks at the client (verify via httpx mock transport).
  - Upstream 503 surfaces as a 503 with the upstream body preserved.

- **Manual smoke test** (post-deploy, on the actual server + laptop):
  - Create API key in web UI.
  - Configure laptop opencode per the new docs.
  - Run `opencode run "list files in this project"` in a small project on the
    laptop, verify the agent reads local files, writes a small change, and
    that `last_used_at` updates in the web UI's API Keys page.

## Migration / rollout

- No data migration. New route is additive.
- No version bump strictly required, but bumping to 0.2.1 makes the release
  visible in changelogs (Sven's call during planning).
- Nginx change is a single `location` block addition; revertible.

## Decisions locked in during spec review

- **API key lives in the rendered config file, not in an env var.** The
  bootstrap script renders a template into `~/.config/opencode/opencode.json`
  (mode 0600) with the key substituted in directly. Rationale: avoids the
  unverified assumption that opencode's JSON loader does shell-style `$VAR`
  expansion; no shell-rc edit needed; security delta vs. an env var is
  negligible (env vars are equally readable via `/proc/<pid>/environ` to
  anyone who can read a 0600 file). The bootstrap script also keeps a
  separate copy of the raw key in `~/.config/balu-code/api_key` (0600) so
  re-running the script without `--new-key` doesn't re-prompt.
- **Ship `scripts/bootstrap-remote-client.sh`.** Downloads opencode binary,
  verifies checksum (same pinned sha256 as `opencode_runtime.py`), prompts
  for API key on first run, renders the config template. Idempotent:
  re-running on an already-bootstrapped host re-verifies the binary and
  re-renders the config without clobbering the key.
