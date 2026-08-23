"""Tests for applying a config change to the opencode runtime.

The owning-worker path (stop + respawn) needs a real opencode binary and is
covered by the integration smoke test, not here. What these tests pin down is
the part that used to be silently wrong: the config file is rewritten in every
case, and a worker that does not own the process reports back honestly instead
of implying the change took effect.
"""

from __future__ import annotations

import json

import pytest

from plugin.config import BaluCodePluginConfig
from plugin.deps import set_opencode, set_opencode_password
from plugin.services.opencode_runtime import ServerHandle
from plugin.services.runtime_manager import apply_config_to_runtime


class _FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_writes_opencode_json_without_a_runtime(tmp_path):
    cfg = BaluCodePluginConfig(chat_model="qwen3.8-code:latest", context_window=32768)

    restarted = await apply_config_to_runtime(tmp_path, cfg)

    assert restarted is False
    payload = json.loads((tmp_path / "opencode.json").read_text())
    assert payload["model"] == "ollama/qwen3.8-code:latest"


@pytest.mark.asyncio
async def test_attached_worker_rewrites_config_but_keeps_hands_off(tmp_path):
    """process=None means a sibling worker owns the server — never kill it."""
    client = _FakeClient()
    set_opencode(ServerHandle(process=None, port=4096, log_fd=None), client)
    set_opencode_password("secret")
    cfg = BaluCodePluginConfig(chat_model="qwen3.8-code:latest")

    restarted = await apply_config_to_runtime(tmp_path, cfg)

    assert restarted is False
    assert client.closed is False
    payload = json.loads((tmp_path / "opencode.json").read_text())
    assert payload["model"] == "ollama/qwen3.8-code:latest"


@pytest.mark.asyncio
async def test_read_only_permission_is_carried_into_the_rewrite(tmp_path):
    cfg = BaluCodePluginConfig()

    await apply_config_to_runtime(tmp_path, cfg, file_write_allowed=False)

    payload = json.loads((tmp_path / "opencode.json").read_text())
    assert payload["permission"] == {"edit": "deny", "bash": "deny"}
