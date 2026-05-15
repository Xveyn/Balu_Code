# Remote Coding Agent Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a client laptop run opencode locally against a BaluHost-hosted Ollama, authenticating via a BaluHost API key.

**Architecture:** New plugin route `ANY /api/plugins/balu_code/ollama/{path:path}` gated by the existing `get_current_user` (which already accepts both JWT and `balu_…` keys). Route hands off to `plugin/services/ollama_proxy.py`, a thin streaming proxy backed by `httpx.AsyncClient`. Nginx gets one carve-out `location` block with `auth_basic off` for that path. Client install ships as `docs/remote-client.md` + `scripts/bootstrap-remote-client.sh` + an `opencode.json` template that env-expands `$BALU_API_KEY`.

**Tech Stack:** Python 3.11, FastAPI, httpx (streaming), pytest + respx (test mocking), bash (bootstrap script), nginx config snippet.

**Spec:** `docs/superpowers/specs/2026-05-15-remote-coding-agent-client-design.md`

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `plugin/services/ollama_proxy.py` | **new** | Pure async function `proxy_request(request, path, *, base_url, transport=None)` → `StreamingResponse`. Header filtering, body forwarding, streamed response. |
| `plugin/routes.py` | modify | Add `ollama_proxy` route inside `build_router()`. |
| `plugin/tests/test_ollama_proxy.py` | **new** | Unit tests for the proxy function in isolation (no FastAPI). |
| `plugin/tests/test_routes_ollama_proxy.py` | **new** | Route-level tests (auth gate + integration via ASGI). |
| `nginx.example.conf` | **new** at `docs/remote-client/nginx.example.conf` | Documented `location` block for ops. |
| `docs/remote-client.md` | **new** | Client install guide (manual + bootstrap-script paths). |
| `docs/remote-client/opencode.json.tmpl` | **new** | Template the bootstrap script renders. |
| `scripts/bootstrap-remote-client.sh` | **new** | Idempotent client bootstrap (download binary, verify checksum, write config, prompt for key). |
| `docs/CHANGELOG.md` | modify | 0.2.1 entry. |
| `plugin/plugin.json`, `pyproject.toml` | modify | Bump version to 0.2.1. |
| `README.md` | modify | One-line pointer to `docs/remote-client.md`. |

Files that change together stay together — proxy logic lives in `services/`, the route just forwards, tests mirror that split.

---

## Task 1: Proxy function skeleton + hop-by-hop header filter

**Files:**
- Create: `plugin/services/ollama_proxy.py`
- Test: `plugin/tests/test_ollama_proxy.py`

- [ ] **Step 1: Write the failing test for hop-by-hop filter**

`plugin/tests/test_ollama_proxy.py`:

```python
"""Tests for the bare Ollama proxy helper (no FastAPI route surface)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from plugin.services.ollama_proxy import _HEADERS_TO_DROP, proxy_request


def test_headers_to_drop_covers_hop_by_hop_and_auth():
    for h in (
        "connection",
        "keep-alive",
        "transfer-encoding",
        "host",
        "content-length",
        "authorization",
    ):
        assert h in _HEADERS_TO_DROP
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest plugin/tests/test_ollama_proxy.py::test_headers_to_drop_covers_hop_by_hop_and_auth -v`
Expected: FAIL — `plugin.services.ollama_proxy` does not exist yet.

- [ ] **Step 3: Create the proxy module with the filter set**

`plugin/services/ollama_proxy.py`:

```python
"""HTTP proxy from inbound FastAPI requests to the local Ollama server.

Pure-function design: no module-level state, no class. The route wires this
in alongside the existing get_current_user auth dependency. The transport
parameter exists so tests can inject httpx.MockTransport without monkey-
patching.

Headers we strip on the way upstream:

- Hop-by-hop (RFC 7230 §6.1): connection, keep-alive, te, trailers,
  transfer-encoding, upgrade, proxy-authenticate, proxy-authorization.
- Routing identity that httpx must set itself: host, content-length.
- End-to-end but plugin-private: authorization — the inbound Bearer key
  authenticates the client to BaluHost, it must not leak to Ollama.
"""

from __future__ import annotations

import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse

_HEADERS_TO_DROP: frozenset[str] = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
        "authorization",
    }
)


async def proxy_request(
    request: Request,
    path: str,
    *,
    base_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = 600.0,
) -> StreamingResponse:
    raise NotImplementedError
```

- [ ] **Step 4: Re-run the test and verify it passes**

Run: `pytest plugin/tests/test_ollama_proxy.py::test_headers_to_drop_covers_hop_by_hop_and_auth -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/services/ollama_proxy.py plugin/tests/test_ollama_proxy.py
git commit -m "feat(ollama_proxy): scaffold proxy module with hop-by-hop + auth header filter"
```

---

## Task 2: Proxy happy path — GET, status + body pass-through

**Files:**
- Modify: `plugin/services/ollama_proxy.py`
- Modify: `plugin/tests/test_ollama_proxy.py`

- [ ] **Step 1: Write the failing test**

Append to `plugin/tests/test_ollama_proxy.py`:

```python
def _wrap_proxy(base_url: str, transport: httpx.AsyncBaseTransport) -> TestClient:
    """Mount the proxy on a bare FastAPI app so we can hit it through TestClient."""
    app = FastAPI()

    @app.api_route("/proxy/{path:path}", methods=["GET", "POST"])
    async def _entry(path: str, request: Request):
        return await proxy_request(
            request, path, base_url=base_url, transport=transport
        )

    return TestClient(app)


def test_get_request_forwards_status_and_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:14b"}]})

    client = _wrap_proxy("http://upstream.test", httpx.MockTransport(handler))
    r = client.get("/proxy/api/tags")
    assert r.status_code == 200
    assert r.json() == {"models": [{"name": "qwen2.5-coder:14b"}]}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest plugin/tests/test_ollama_proxy.py::test_get_request_forwards_status_and_body -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement the proxy function**

Replace the `raise NotImplementedError` body in `plugin/services/ollama_proxy.py`:

```python
async def proxy_request(
    request: Request,
    path: str,
    *,
    base_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = 600.0,
) -> StreamingResponse:
    target = f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    forward_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _HEADERS_TO_DROP
    }
    body = await request.body()

    client = httpx.AsyncClient(transport=transport, timeout=timeout)
    upstream_req = client.build_request(
        method=request.method,
        url=target,
        headers=forward_headers,
        content=body,
    )
    upstream = await client.send(upstream_req, stream=True)

    response_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in _HEADERS_TO_DROP
    }

    async def body_iter():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        body_iter(),
        status_code=upstream.status_code,
        headers=response_headers,
    )


__all__ = ["proxy_request"]
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest plugin/tests/test_ollama_proxy.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/services/ollama_proxy.py plugin/tests/test_ollama_proxy.py
git commit -m "feat(ollama_proxy): proxy GET requests with status/body pass-through"
```

---

## Task 3: POST body forwarding + streamed chunked response

**Files:**
- Modify: `plugin/tests/test_ollama_proxy.py`

(The function from Task 2 already handles both — these tests pin that behaviour and catch regressions.)

- [ ] **Step 1: Write the failing tests**

Append to `plugin/tests/test_ollama_proxy.py`:

```python
def test_post_request_forwards_body_bytes():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        seen["content_type"] = request.headers.get("content-type")
        return httpx.Response(200, json={"ok": True})

    client = _wrap_proxy("http://upstream.test", httpx.MockTransport(handler))
    payload = b'{"model": "qwen2.5-coder:14b", "messages": []}'
    r = client.post(
        "/proxy/api/chat",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 200
    assert seen["body"] == payload
    assert seen["content_type"] == "application/json"


def test_streaming_response_chunks_pass_through_in_order():
    chunks = [b'{"chunk":1}\n', b'{"chunk":2}\n', b'{"chunk":3}\n']

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(b"".join(chunks)))

    client = _wrap_proxy("http://upstream.test", httpx.MockTransport(handler))
    with client.stream("POST", "/proxy/api/chat") as r:
        assert r.status_code == 200
        got = b"".join(r.iter_raw())
    assert got == b"".join(chunks)


def test_authorization_header_does_not_leak_upstream():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={})

    client = _wrap_proxy("http://upstream.test", httpx.MockTransport(handler))
    r = client.get(
        "/proxy/api/tags",
        headers={"authorization": "Bearer balu_secret123"},
    )
    assert r.status_code == 200
    assert seen["authorization"] is None
```

- [ ] **Step 2: Run the tests**

Run: `pytest plugin/tests/test_ollama_proxy.py -v`
Expected: all five tests PASS (existing implementation already covers these — the tests are regression guards).

- [ ] **Step 3: Commit**

```bash
git add plugin/tests/test_ollama_proxy.py
git commit -m "test(ollama_proxy): pin POST body, streaming chunks, Authorization stripping"
```

---

## Task 4: Upstream errors pass through

**Files:**
- Modify: `plugin/tests/test_ollama_proxy.py`

- [ ] **Step 1: Write the failing test**

Append to `plugin/tests/test_ollama_proxy.py`:

```python
def test_upstream_5xx_passes_through_with_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "ollama warming up"})

    client = _wrap_proxy("http://upstream.test", httpx.MockTransport(handler))
    r = client.get("/proxy/api/tags")
    assert r.status_code == 503
    assert r.json() == {"error": "ollama warming up"}


def test_upstream_connect_failure_surfaces_as_502():
    """No upstream listening on this port; httpx raises, we let FastAPI surface it.

    We deliberately do NOT wrap the proxy in a try/except — that would mask
    bugs. FastAPI converts unhandled exceptions to 500. The test pins that
    behaviour so a future 'add error handling' change is intentional.
    """

    client = _wrap_proxy("http://127.0.0.1:1", transport=None)
    r = client.get("/proxy/api/tags")
    assert r.status_code == 500  # FastAPI default for unhandled exceptions
```

- [ ] **Step 2: Run the tests**

Run: `pytest plugin/tests/test_ollama_proxy.py -v`
Expected: first new test PASSes immediately. Second new test may need `raise_server_exceptions=False` on TestClient.

- [ ] **Step 3: Fix the connect-failure test if needed**

If the second test fails because TestClient re-raises the connection error, replace `client = _wrap_proxy(...)` body for that test:

```python
def test_upstream_connect_failure_surfaces_as_500():
    app = FastAPI()

    @app.api_route("/proxy/{path:path}", methods=["GET"])
    async def _entry(path: str, request: Request):
        return await proxy_request(
            request, path, base_url="http://127.0.0.1:1"
        )

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/proxy/api/tags")
    assert r.status_code == 500
```

Run again: `pytest plugin/tests/test_ollama_proxy.py -v` → all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add plugin/tests/test_ollama_proxy.py
git commit -m "test(ollama_proxy): pin 5xx pass-through and connect-failure surfacing"
```

---

## Task 5: Route — auth gate

**Files:**
- Modify: `plugin/routes.py`
- Create: `plugin/tests/test_routes_ollama_proxy.py`

- [ ] **Step 1: Write the failing auth test**

`plugin/tests/test_routes_ollama_proxy.py`:

```python
"""Tests for the /ollama/{path} route — auth gate, path passthrough."""

from __future__ import annotations

import httpx
import pytest
from app.api.deps import get_current_user
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from plugin.config import BaluCodePluginConfig
from plugin.deps import get_plugin_config
from plugin.routes import build_router


def _app(ollama_base_url: str = "http://upstream.test") -> FastAPI:
    """Mount the router and inject just the deps this route needs."""
    app = FastAPI()
    app.include_router(build_router(), prefix="/api/plugins/balu_code")
    cfg = BaluCodePluginConfig(ollama_base_url=ollama_base_url)
    app.dependency_overrides[get_plugin_config] = lambda: cfg
    return app


@pytest.mark.asyncio
async def test_ollama_route_requires_authentication():
    app = _app()

    async def _denied():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    app.dependency_overrides[get_current_user] = _denied
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/plugins/balu_code/ollama/api/tags")
    assert r.status_code == 401
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest plugin/tests/test_routes_ollama_proxy.py::test_ollama_route_requires_authentication -v`
Expected: FAIL — route does not exist (404).

- [ ] **Step 3: Add the route in `plugin/routes.py`**

Add this import near the top of `plugin/routes.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
```

(The existing import line already pulls `APIRouter, Depends, HTTPException, Query, status` — add `Request` to it.)

Add this import block alongside the other service imports:

```python
from .services.ollama_proxy import proxy_request
```

Add this route inside `build_router()`, after the `/runtime/credentials` route:

```python
    @router.api_route(
        "/ollama/{path:path}",
        methods=["GET", "POST"],
        tags=["balu_code"],
    )
    async def ollama_proxy_route(
        path: str,
        request: Request,
        _user: UserPublic = Depends(get_current_user),
        config: BaluCodePluginConfig = Depends(get_plugin_config),
    ):
        return await proxy_request(request, path, base_url=config.ollama_base_url)
```

- [ ] **Step 4: Re-run the auth test**

Run: `pytest plugin/tests/test_routes_ollama_proxy.py::test_ollama_route_requires_authentication -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/routes.py plugin/tests/test_routes_ollama_proxy.py
git commit -m "feat(routes): add /ollama/{path} proxy route gated by get_current_user"
```

---

## Task 6: Route — happy-path integration with mocked upstream

**Files:**
- Modify: `plugin/tests/test_routes_ollama_proxy.py`

- [ ] **Step 1: Write the failing test**

Append to `plugin/tests/test_routes_ollama_proxy.py`:

```python
@pytest.mark.asyncio
async def test_ollama_route_proxies_tags_request():
    import respx

    app = _app()
    transport = ASGITransport(app=app)

    with respx.mock(base_url="http://upstream.test", assert_all_called=False) as mock:
        mock.get("/api/tags").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:14b"}]})
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/plugins/balu_code/ollama/api/tags")

    assert r.status_code == 200
    assert r.json() == {"models": [{"name": "qwen2.5-coder:14b"}]}


@pytest.mark.asyncio
async def test_ollama_route_proxies_chat_post_with_streaming():
    import respx

    app = _app()
    transport = ASGITransport(app=app)
    chunks = b'{"chunk":1}\n{"chunk":2}\n{"chunk":3}\n'

    with respx.mock(base_url="http://upstream.test", assert_all_called=False) as mock:
        mock.post("/api/chat").mock(return_value=httpx.Response(200, content=chunks))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/plugins/balu_code/ollama/api/chat",
                content=b'{"model":"qwen2.5-coder:14b","messages":[]}',
                headers={"content-type": "application/json"},
            )

    assert r.status_code == 200
    assert r.content == chunks
```

- [ ] **Step 2: Run the tests**

Run: `pytest plugin/tests/test_routes_ollama_proxy.py -v`
Expected: both new tests PASS.

- [ ] **Step 3: Commit**

```bash
git add plugin/tests/test_routes_ollama_proxy.py
git commit -m "test(routes): integration coverage for /ollama proxy (tags + streaming chat)"
```

---

## Task 7: Nginx config snippet

**Files:**
- Create: `docs/remote-client/nginx.example.conf`

- [ ] **Step 1: Write the snippet**

`docs/remote-client/nginx.example.conf`:

```nginx
# Drop this inside your existing BaluHost server { ... } block.
# It carves out /api/plugins/balu_code/ollama/ from the outer auth_basic
# wall so the FastAPI Bearer-token check (BaluHost API keys) is the sole
# auth surface for that path.
#
# Everything else under /api/ and / keeps the existing Basic Auth.

location /api/plugins/balu_code/ollama/ {
    auth_basic off;

    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Streaming: token-by-token chat responses must not be buffered.
    proxy_buffering off;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;

    # Ollama embedding / image batches can be a few MiB.
    client_max_body_size 64m;
}
```

- [ ] **Step 2: Verify the file lints in nginx -t locally if accessible**

Skip if nginx isn't installed on this host; the actual deployment will run `sudo nginx -t` after copying this in.

- [ ] **Step 3: Commit**

```bash
git add docs/remote-client/nginx.example.conf
git commit -m "docs(remote-client): nginx location snippet for /ollama/ carve-out"
```

---

## Task 8: opencode config template

**Files:**
- Create: `docs/remote-client/opencode.json.tmpl`

- [ ] **Step 1: Write the template**

`docs/remote-client/opencode.json.tmpl`:

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
        "headers": {
          "Authorization": "Bearer __API_KEY__"
        }
      },
      "models": {
        "__MODEL__": {
          "name": "__MODEL__",
          "options": {
            "options": { "num_ctx": __NUM_CTX__ }
          }
        }
      }
    }
  }
}
```

(`__PLACEHOLDER__` markers are replaced by the bootstrap script; no shell env-var expansion is required at runtime, so the template works regardless of whether opencode supports `$VAR` in JSON.)

- [ ] **Step 2: Commit**

```bash
git add docs/remote-client/opencode.json.tmpl
git commit -m "docs(remote-client): opencode.json template for bootstrap script"
```

---

## Task 9: Bootstrap script

**Files:**
- Create: `scripts/bootstrap-remote-client.sh`

- [ ] **Step 1: Write the script**

`scripts/bootstrap-remote-client.sh`:

```bash
#!/usr/bin/env bash
# Bootstrap a client laptop to run opencode locally against a BaluHost remote Ollama.
#
# What it does (idempotent):
#   1. Downloads the pinned opencode binary if missing, verifies sha256.
#   2. Writes ~/.config/opencode/opencode.json from the in-repo template.
#   3. Prompts once for the BaluHost API key, saves it to
#      ~/.config/balu-code/api_key (mode 0600).
#   4. Prints the export line the user needs in their shell rc.
#
# Re-running on an already-bootstrapped host:
#   - re-verifies the binary,
#   - re-renders the config (picks up new server URL / model),
#   - keeps the saved API key unless the user passes --new-key.

set -euo pipefail

OPENCODE_VERSION="1.14.50"
OPENCODE_TRIPLE="linux-x64"
OPENCODE_SHA256="2c4abf29d5765f535f10ffec748aa38939d5441750abbdb5001a4307d33349ae"
OPENCODE_URL="https://github.com/sst/opencode/releases/download/v${OPENCODE_VERSION}/opencode-${OPENCODE_TRIPLE}.tar.gz"

INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/balu-code-client}"
BINARY_PATH="${INSTALL_DIR}/opencode"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
CONFIG_FILE="${CONFIG_DIR}/opencode.json"
KEY_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/balu-code"
KEY_FILE="${KEY_DIR}/api_key"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_PATH="${REPO_ROOT}/docs/remote-client/opencode.json.tmpl"

NEW_KEY=0
for arg in "$@"; do
    case "$arg" in
        --new-key) NEW_KEY=1 ;;
        -h|--help)
            echo "Usage: $(basename "$0") [--new-key]"
            echo "Env: BASE_URL, MODEL, NUM_CTX (defaults shown when prompted)"
            exit 0
            ;;
    esac
done

prompt() {
    local prompt_text="$1" default="$2" reply
    read -rp "${prompt_text} [${default}]: " reply
    echo "${reply:-$default}"
}

# --- 1. Binary ---
mkdir -p "${INSTALL_DIR}"
need_download=1
if [[ -f "${BINARY_PATH}" ]]; then
    actual="$(sha256sum "${BINARY_PATH}" | awk '{print $1}')"
    if [[ "${actual}" == "${OPENCODE_SHA256}" ]]; then
        echo "opencode binary already present and verified."
        need_download=0
    else
        echo "opencode binary checksum mismatch; will re-download."
    fi
fi
if [[ "${need_download}" -eq 1 ]]; then
    echo "Downloading opencode ${OPENCODE_VERSION} (${OPENCODE_TRIPLE})..."
    tmpdir="$(mktemp -d)"
    trap 'rm -rf "${tmpdir}"' EXIT
    curl -fsSL "${OPENCODE_URL}" -o "${tmpdir}/opencode.tar.gz"
    tar -xzf "${tmpdir}/opencode.tar.gz" -C "${tmpdir}"
    extracted="$(find "${tmpdir}" -type f -name opencode -perm -u+x | head -n1)"
    if [[ -z "${extracted}" ]]; then
        echo "could not find opencode binary inside tarball" >&2
        exit 1
    fi
    actual="$(sha256sum "${extracted}" | awk '{print $1}')"
    if [[ "${actual}" != "${OPENCODE_SHA256}" ]]; then
        echo "checksum mismatch: expected ${OPENCODE_SHA256}, got ${actual}" >&2
        exit 1
    fi
    mv "${extracted}" "${BINARY_PATH}"
    chmod 0755 "${BINARY_PATH}"
    echo "opencode installed to ${BINARY_PATH}"
fi

# --- 2. API key ---
mkdir -p "${KEY_DIR}"
chmod 0700 "${KEY_DIR}"
if [[ -f "${KEY_FILE}" && "${NEW_KEY}" -eq 0 ]]; then
    echo "Reusing existing API key in ${KEY_FILE}."
else
    echo
    echo "Create a BaluHost API key:"
    echo "  https://YOUR-BALUHOST/users  →  Profile  →  API Keys  →  New"
    echo "It must start with 'balu_'."
    read -rsp "Paste API key: " api_key
    echo
    if [[ -z "${api_key}" || "${api_key}" != balu_* ]]; then
        echo "Refusing to save: key is empty or has no 'balu_' prefix." >&2
        exit 1
    fi
    umask 077
    printf '%s' "${api_key}" > "${KEY_FILE}"
    chmod 0600 "${KEY_FILE}"
    echo "API key saved to ${KEY_FILE}."
fi

# --- 3. Config ---
mkdir -p "${CONFIG_DIR}"
api_key_value="$(cat "${KEY_FILE}")"
base_url="${BASE_URL:-$(prompt "BaluHost base URL (without trailing slash)" "https://baluhost.example")}"
model="${MODEL:-$(prompt "Default model" "qwen2.5-coder:14b")}"
num_ctx="${NUM_CTX:-$(prompt "Context window (num_ctx)" "32768")}"

full_base="${base_url%/}/api/plugins/balu_code/ollama/api"

# Use python rather than sed to keep escaping sane (api keys contain '/' and '+').
python3 - "${TEMPLATE_PATH}" "${CONFIG_FILE}" \
    "${full_base}" "${api_key_value}" "${model}" "${num_ctx}" <<'PY'
import sys, pathlib
tmpl_path, out_path, base_url, api_key, model, num_ctx = sys.argv[1:]
tmpl = pathlib.Path(tmpl_path).read_text()
out = (tmpl
       .replace("__BASE_URL__", base_url)
       .replace("__API_KEY__", api_key)
       .replace("__MODEL__", model)
       .replace("__NUM_CTX__", str(int(num_ctx))))
pathlib.Path(out_path).write_text(out)
PY
chmod 0600 "${CONFIG_FILE}"
echo "opencode config written to ${CONFIG_FILE}"

# --- 4. PATH hint ---
echo
echo "Done. Add this to your shell rc if ${INSTALL_DIR} isn't on PATH yet:"
echo "  export PATH=\"${INSTALL_DIR}:\$PATH\""
echo
echo "Then: cd into a project and run:  opencode"
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/bootstrap-remote-client.sh
```

- [ ] **Step 3: Smoke-test the script with a temp HOME**

Run:
```bash
HOME=$(mktemp -d) BASE_URL=https://example.test MODEL=qwen2.5-coder:14b NUM_CTX=32768 \
  bash -c 'echo "balu_testkey_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" | scripts/bootstrap-remote-client.sh'
```
(The script will actually download the real opencode binary the first time. If you want to skip the network hop for the smoke test, copy a fake binary to `$HOME/.local/share/balu-code-client/opencode` with the right sha256 first — or skip this step if you only want to lint the script.)

Expected: exits 0, writes `$HOME/.config/opencode/opencode.json` and `$HOME/.config/balu-code/api_key`.

If you want to skip the network download during smoke-test, instead just check the script passes `bash -n`:
```bash
bash -n scripts/bootstrap-remote-client.sh
```
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add scripts/bootstrap-remote-client.sh
git commit -m "feat(scripts): bootstrap-remote-client.sh — install opencode + render config + save key"
```

---

## Task 10: Client install documentation

**Files:**
- Create: `docs/remote-client.md`

- [ ] **Step 1: Write the guide**

`docs/remote-client.md`:

````markdown
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
````

- [ ] **Step 2: Commit**

```bash
git add docs/remote-client.md
git commit -m "docs(remote-client): client install guide (bootstrap + manual) and ops carve-out"
```

---

## Task 11: Version bump + CHANGELOG + README pointer

**Files:**
- Modify: `plugin/plugin.json`
- Modify: `pyproject.toml`
- Modify: `docs/CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 1: Bump version**

`plugin/plugin.json` — change `"version": "0.2.0"` → `"version": "0.2.1"`.

`pyproject.toml` — change `version = "0.2.0"` → `version = "0.2.1"`.

- [ ] **Step 2: Append CHANGELOG entry**

Add at the top of `docs/CHANGELOG.md` (just under the `# Changelog` heading, above `## 0.2.0 — 2026-05-14`):

```markdown
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
```

- [ ] **Step 3: README pointer**

In `README.md`, under the `## Docs` list, add:

```markdown
- [`docs/remote-client.md`](docs/remote-client.md) — run opencode on a client laptop against the BaluHost server
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest plugin/tests -v`
Expected: all tests pass (291 prior + ~10 new).

- [ ] **Step 5: Run ruff**

Run: `ruff check plugin/ scripts/`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add plugin/plugin.json pyproject.toml docs/CHANGELOG.md README.md
git commit -m "chore: bump to 0.2.1 + CHANGELOG entry for remote-client workflow"
```

---

## Verification checklist (post-implementation, before declaring done)

- [ ] `pytest plugin/tests -v` — all tests pass.
- [ ] `ruff check plugin/ scripts/` — clean.
- [ ] `bash -n scripts/bootstrap-remote-client.sh` — script parses.
- [ ] Manual: in a `tmp` HOME, run the bootstrap script end-to-end with a
      dummy API key, inspect the generated `opencode.json`.
- [ ] Manual: paste the nginx snippet into a local nginx config, run
      `nginx -t`, confirm it parses.
- [ ] Manual smoke test on the actual server + laptop (post-deploy):
  - Issue a real API key, configure laptop, run `opencode run "list files"`
    in a small project.
  - Verify the agent reads local files and writes a small change.
  - Verify `last_used_at` updates in the web UI's API Keys page.
