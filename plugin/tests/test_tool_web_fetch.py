"""Tests for web_fetch tool — offline fixtures via httpx.MockTransport."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from plugin.services.cancel import CancelToken
from plugin.services.tools.base import ToolContext
from plugin.services.tools.web_fetch import WebFetchArgs, WebFetchTool


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        project_root=tmp_path,
        project_id=1,
        turn_id="t_test",
        cancel_token=CancelToken(),
    )


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_html_extraction_via_trafilatura(ctx: ToolContext) -> None:
    def handler(request):
        return httpx.Response(
            200,
            text="<html><body><h1>Hello</h1><p>World-content-1234</p></body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )

    tool = WebFetchTool(transport=_transport(handler))
    result = await tool.execute(WebFetchArgs(url="https://example.com/"), ctx)
    assert result.status == "ok"
    assert "World-content-1234" in result.text


@pytest.mark.asyncio
async def test_non_html_returned_raw(ctx: ToolContext) -> None:
    def handler(request):
        return httpx.Response(
            200,
            text='{"hello": "world"}',
            headers={"content-type": "application/json"},
        )

    tool = WebFetchTool(transport=_transport(handler))
    result = await tool.execute(WebFetchArgs(url="https://example.com/api"), ctx)
    assert result.status == "ok"
    assert '"hello": "world"' in result.text


@pytest.mark.asyncio
async def test_max_bytes_truncates(ctx: ToolContext) -> None:
    big_text = "x" * 2000

    def handler(request):
        return httpx.Response(200, text=big_text, headers={"content-type": "text/plain"})

    tool = WebFetchTool(transport=_transport(handler))
    result = await tool.execute(
        WebFetchArgs(url="https://example.com/big", max_bytes=1024),
        ctx,
    )
    assert result.status == "ok"
    assert len(result.text.encode("utf-8")) <= 1024


@pytest.mark.asyncio
async def test_rejects_localhost_by_hostname(ctx: ToolContext) -> None:
    tool = WebFetchTool()
    result = await tool.execute(WebFetchArgs(url="http://localhost:8000/"), ctx)
    assert result.status == "error"
    assert "localhost" in result.error.lower() or "private" in result.error.lower()


@pytest.mark.asyncio
async def test_rejects_private_ip(ctx: ToolContext) -> None:
    tool = WebFetchTool()
    result = await tool.execute(WebFetchArgs(url="http://10.0.0.1/"), ctx)
    assert result.status == "error"


@pytest.mark.asyncio
async def test_rejects_link_local(ctx: ToolContext) -> None:
    tool = WebFetchTool()
    result = await tool.execute(WebFetchArgs(url="http://169.254.169.254/"), ctx)
    assert result.status == "error"


@pytest.mark.asyncio
async def test_rejects_ipv6_loopback(ctx: ToolContext) -> None:
    tool = WebFetchTool()
    result = await tool.execute(WebFetchArgs(url="http://[::1]/"), ctx)
    assert result.status == "error"


def test_risk_is_network() -> None:
    assert WebFetchTool.risk == "network"
