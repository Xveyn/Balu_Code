# Remote Coding Agent Client

Run opencode locally on your laptop while the LLM stays on the BaluHost GPU server. Files on your laptop, model on the server.

## Prerequisites

- BaluHost ≥ 1.29 reachable from the client (the URL you use in a browser).
- BaluHost user account.
- Linux x86_64 client. (macOS / Windows: the same template works, swap the
  download URL and checksum to the matching opencode release asset.)

## One-shot install (recommended)

```bash
git clone https://github.com/Xveyn/Balu_Code.git
cd Balu_Code
./scripts/bootstrap-remote-client.sh
```

The script asks for:
- your BaluHost base URL (e.g. `https://baluhost.example`),
- the default model (e.g. `qwen2.5-coder:14b`),
- the context window (`num_ctx`),
- a BaluHost API key.

To create the API key: log into BaluHost → **Profile → API Keys → New**.
Copy the key once (it starts with `balu_`); the server only stores a hash.

After the script finishes, add the install dir to `PATH` (the script prints
the line) and run:

```bash
cd ~/projects/some-repo
opencode
```

## Manual install

1. Download opencode 1.14.50 from the upstream release and verify SHA-256
   `2c4abf29d5765f535f10ffec748aa38939d5441750abbdb5001a4307d33349ae`.
2. Create a BaluHost API key (Profile → API Keys → New).
3. Copy `docs/remote-client/opencode.json.tmpl` to
   `~/.config/opencode/opencode.json` and replace the four `__PLACEHOLDER__`
   tokens with your values:
   - `__BASE_URL__` → `https://<baluhost>/api/plugins/balu_code/ollama/api`
   - `__API_KEY__` → your `balu_…` key
   - `__MODEL__` → e.g. `qwen2.5-coder:14b`
   - `__NUM_CTX__` → e.g. `32768`
4. `chmod 0600 ~/.config/opencode/opencode.json` (it contains a credential).

## Rotating the API key

```bash
./scripts/bootstrap-remote-client.sh --new-key
```

This re-prompts for a key, re-renders the config, leaves the binary alone.
Revoke the old key in the BaluHost web UI to invalidate it server-side.

## What the server admin needs to do once

Carve `/api/plugins/balu_code/ollama/` out of nginx Basic Auth — drop the
snippet from [`docs/remote-client/nginx.example.conf`](remote-client/nginx.example.conf)
into the BaluHost `server { ... }` block, then `sudo nginx -t && sudo systemctl reload nginx`.

## Troubleshooting

- **401 on every request** — key is wrong, revoked, expired, or shadowed by
  nginx Basic Auth still being active for `/ollama/`. Check the API Keys
  page in BaluHost; check the nginx snippet is in place.
- **opencode hangs on first message** — Ollama is loading the model; that's
  normal for the first request after server restart. Server-side
  `Balu Code → System` tab shows loaded models.
- **`SSL certificate problem`** — your laptop doesn't trust the BaluHost
  cert. Use Let's Encrypt server-side, or export `NODE_EXTRA_CA_CERTS=/path/to/ca.pem`
  before launching opencode.

## Limitations (v1)

- API keys grant access at the user level; a leaked key can hit any BaluHost
  endpoint that user has access to. Workaround: create a low-privilege user
  for the coding agent and issue keys against that user.
- No per-key rate limit; a leaked key can hammer the GPU until you revoke it.
- Client-side sessions don't appear in the BaluHost web UI session list or
  audit log. Server-side ones still do.
