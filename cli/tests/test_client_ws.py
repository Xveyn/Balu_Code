"""Tests for client/ws.py — real local websockets server."""

from __future__ import annotations

import json

import pytest
import websockets
from balu_code_cli.client.ws import connect


async def _make_server(handler):
    server = await websockets.serve(handler, "localhost", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


@pytest.mark.asyncio
async def test_send_message_sends_user_message_frame():
    received = []

    async def handler(ws):
        raw = await ws.recv()
        received.append(json.loads(raw))
        # send turn_end so client doesn't hang
        await ws.send(
            json.dumps(
                {
                    "type": "turn_end",
                    "turn_id": "t_1",
                    "total_tokens": 0,
                    "iterations": 0,
                    "stop_reason": "done",
                }
            )
        )

    server, port = await _make_server(handler)
    try:
        async with connect(f"http://localhost:{port}", "test_key", 1) as ws:
            await ws.send_message("hello world")
    finally:
        server.close()
        await server.wait_closed()

    assert received[0]["type"] == "user_message"
    assert received[0]["content"] == "hello world"


@pytest.mark.asyncio
async def test_receive_parses_token_event():
    async def handler(ws):
        await ws.recv()  # consume user_message
        await ws.send(json.dumps({"type": "token", "content": "Hi"}))
        await ws.send(
            json.dumps(
                {
                    "type": "turn_end",
                    "turn_id": "t_1",
                    "total_tokens": 1,
                    "iterations": 1,
                    "stop_reason": "done",
                }
            )
        )

    server, port = await _make_server(handler)
    try:
        async with connect(f"http://localhost:{port}", "key", 1) as ws:
            await ws.send_message("hi")
            ev = await ws.receive()
            assert ev.type == "token"
            assert ev.content == "Hi"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_send_approval_sends_approval_frame():
    received = []

    async def handler(ws):
        await ws.recv()  # user_message
        # send approval_request
        await ws.send(
            json.dumps(
                {
                    "type": "approval_request",
                    "tool_call_id": "tc_1",
                    "tool": "write_file",
                    "args": {},
                    "risk": "write",
                }
            )
        )
        raw = await ws.recv()
        received.append(json.loads(raw))
        await ws.send(
            json.dumps(
                {
                    "type": "turn_end",
                    "turn_id": "t_1",
                    "total_tokens": 0,
                    "iterations": 1,
                    "stop_reason": "done",
                }
            )
        )

    server, port = await _make_server(handler)
    try:
        async with connect(f"http://localhost:{port}", "key", 1) as ws:
            await ws.send_message("go")
            _ = await ws.receive()  # approval_request
            await ws.send_approval("tc_1", approved=True)
    finally:
        server.close()
        await server.wait_closed()

    assert received[0]["type"] == "approval"
    assert received[0]["tool_call_id"] == "tc_1"
    assert received[0]["approved"] is True


@pytest.mark.asyncio
async def test_send_cancel_sends_cancel_frame():
    received = []

    async def handler(ws):
        await ws.recv()  # user_message
        raw = await ws.recv()
        received.append(json.loads(raw))

    server, port = await _make_server(handler)
    try:
        async with connect(f"http://localhost:{port}", "key", 1) as ws:
            await ws.send_message("go")
            await ws.send_cancel("t_abc")
    finally:
        server.close()
        await server.wait_closed()

    assert received[0]["type"] == "cancel"
    assert received[0]["turn_id"] == "t_abc"
