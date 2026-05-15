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
            if upstream.is_stream_consumed:
                # MockTransport (and any transport that buffers) hands us a
                # response whose body is already loaded — aiter_raw would
                # raise StreamConsumed. Yield the buffered bytes instead.
                if upstream.content:
                    yield upstream.content
            else:
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
