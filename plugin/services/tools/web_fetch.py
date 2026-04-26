"""web_fetch tool — HTTP fetch with SSRF guard + Readability extraction."""

from __future__ import annotations

import ipaddress
import socket
from typing import Optional

import httpx
import trafilatura
from pydantic import BaseModel, Field, HttpUrl

from plugin.services.tools.base import ToolContext, ToolResult

_TIMEOUT_S = 20.0
_MAX_REDIRECTS = 5


class WebFetchArgs(BaseModel):
    url: HttpUrl = Field(..., description="Absolute http(s) URL.")
    max_bytes: int = Field(
        default=500_000,
        ge=1024,
        le=2 * 1024 * 1024,
        description="Maximum bytes of response content to return.",
    )


class WebFetchTool:
    name = "web_fetch"
    description = (
        "Fetch a URL (http/https). Returns readable text extracted from HTML "
        "pages; other content types are returned raw (truncated). Private/"
        "loopback/link-local IPs are blocked."
    )
    args_schema = WebFetchArgs
    risk = "network"

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._transport = transport

    async def execute(self, args: WebFetchArgs, ctx: ToolContext) -> ToolResult:
        url = str(args.url)
        try:
            _guard_host(url)
        except _SSRFBlocked as e1:
            return ToolResult(status="error", text="", error=f"ssrf: {e1}")

        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=_TIMEOUT_S,
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            event_hooks={"response": [_check_redirect_host]},
        ) as client:
            try:
                response = await client.get(url)
            except _SSRFBlocked as e2:
                return ToolResult(status="error", text="", error=f"ssrf after redirect: {e2}")
            except httpx.TooManyRedirects as e3:
                return ToolResult(status="error", text="", error=f"too many redirects: {e3}")
            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as e4:
                return ToolResult(status="error", text="", error=f"fetch failed: {e4}")

        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        raw_bytes = response.content[: args.max_bytes]

        if content_type in ("text/html", "application/xhtml+xml"):
            html = raw_bytes.decode(response.encoding or "utf-8", errors="replace")
            extracted = trafilatura.extract(html) or ""
            text = extracted.strip() or html[: args.max_bytes]
        else:
            text = raw_bytes.decode(response.encoding or "utf-8", errors="replace")

        summary = f"GET {response.url} -> {response.status_code} ({content_type})\n---\n{text}"
        summary_bytes = summary.encode("utf-8")[: args.max_bytes]
        return ToolResult(
            status="ok" if response.is_success else "error",
            text=summary_bytes.decode("utf-8", errors="replace"),
            bytes_out=len(raw_bytes),
            error=None if response.is_success else f"http status {response.status_code}",
        )


class _SSRFBlocked(Exception):
    pass


def _guard_host(url: str) -> None:
    parsed = httpx.URL(url)
    host = parsed.host
    if not host:
        raise _SSRFBlocked(f"no host in url {url}")
    if host.lower() == "localhost":
        raise _SSRFBlocked("localhost is blocked")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e1:
        raise _SSRFBlocked(f"dns failed for {host}: {e1}") from e1
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
            raise _SSRFBlocked(f"{host} resolves to {ip_str} which is not reachable")


async def _check_redirect_host(response) -> None:
    if response.is_redirect:
        location = response.headers.get("location")
        if location:
            target = str(httpx.URL(response.url).join(location))
            _guard_host(target)


__all__ = ["WebFetchArgs", "WebFetchTool"]
