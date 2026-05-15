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
