"""Integration tests against a real opencode binary.

Skipped unless OPENCODE_BINARY env var points to a working binary.
Run with:
    OPENCODE_BINARY=/path/to/opencode uv run python -m pytest plugin/tests/test_opencode_integration.py -v

The session-send test additionally requires Ollama running locally with the
configured model pulled.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    "OPENCODE_BINARY" not in os.environ,
    reason="OPENCODE_BINARY env var not set",
)


@pytest.mark.asyncio
async def test_real_binary_serves_health(tmp_path):
    from plugin.services.opencode_client import OpencodeClient
    from plugin.services.opencode_runtime import start_server, stop_server

    binary = Path(os.environ["OPENCODE_BINARY"])
    cfg_dir = tmp_path
    (cfg_dir / "opencode.json").write_text(
        '{"provider":{"ollama":{"options":{"baseURL":"http://127.0.0.1:11434"}}}}'
    )
    log = tmp_path / "opencode.log"

    handle = await start_server(
        binary=binary,
        config_dir=cfg_dir,
        log_path=log,
        port=0,
        ready_timeout=20.0,
    )
    try:
        async with OpencodeClient(f"http://127.0.0.1:{handle.port}") as client:
            assert await client.health() is True
    finally:
        await stop_server(handle)


@pytest.mark.asyncio
async def test_real_binary_create_session_and_prompt(tmp_path):
    """End-to-end smoke. Requires Ollama on 127.0.0.1:11434 with qwen2.5-coder:14b pulled."""
    from plugin.services.opencode_client import OpencodeClient
    from plugin.services.opencode_runtime import start_server, stop_server

    binary = Path(os.environ["OPENCODE_BINARY"])
    cfg_dir = tmp_path
    (cfg_dir / "opencode.json").write_text(
        '{"model":"ollama/qwen2.5-coder:14b",'
        '"provider":{"ollama":{"options":{"baseURL":"http://127.0.0.1:11434"}}}}'
    )
    log = tmp_path / "opencode.log"
    work = tmp_path / "work"
    work.mkdir()

    handle = await start_server(
        binary=binary,
        config_dir=cfg_dir,
        log_path=log,
        port=0,
        ready_timeout=20.0,
    )
    try:
        async with OpencodeClient(f"http://127.0.0.1:{handle.port}") as client:
            session_id = await client.create_session()
            assert session_id.startswith("ses")
            result = await client.prompt(
                session_id,
                text="reply with exactly: hi",
                model_provider="ollama",
                model_id="qwen2.5-coder:14b",
            )
            assert "info" in result
            assert "parts" in result
            assert len(result["parts"]) > 0
    finally:
        await stop_server(handle)
