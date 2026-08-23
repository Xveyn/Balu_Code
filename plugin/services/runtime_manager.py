"""Apply a changed plugin config to the running opencode runtime.

Why this module exists: opencode reads `<OPENCODE_CONFIG_DIR>/opencode.json`
when it starts. `plugin/__init__.py:on_startup()` writes that file exactly
once, so before this module a config change made through `PUT /config` (or
the web UI Config tab) never reached opencode — the freshly selected model
was missing from `provider.ollama.models`, and its `num_ctx`/`think` options
with it. The symptom is indirect and nasty: opencode keeps answering with the
*old* model, or falls back to Ollama's 4096-token default and silently
truncates its own system prompt until tool calls stop working.

Rewriting the file is only half of it. `Watchdog` in `opencode_runtime.py` is
defined but never started anywhere, so a stopped server is not brought back by
anything — the restart has to happen here, synchronously, and the new handle
has to replace the singletons in `deps.py`.

Multi-worker caveat: BaluHost runs several Uvicorn workers, each with its own
copy of this plugin, but only the worker that won the `runtime.lock` flock
owns the opencode process. Every other worker holds an *attached* handle and
must not kill a process it does not own (`stop_server` refuses, by design).
Such a worker still rewrites `opencode.json` and reports back that no restart
happened, so the caller can tell the operator to restart the backend instead
of pretending the change took effect.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..config import BaluCodePluginConfig
from .opencode_client import OpencodeClient
from .opencode_config import write_opencode_config
from .opencode_runtime import binary_path, start_or_attach_server, stop_server


async def apply_config_to_runtime(
    data_dir: Path,
    cfg: BaluCodePluginConfig,
    *,
    file_write_allowed: bool = True,
) -> bool:
    """Rewrite opencode.json and restart opencode so it picks the config up.

    Returns True when this worker owned the runtime and restarted it, False
    when the config file was rewritten but the running server was left alone
    (no runtime initialised, or this worker is only attached to one owned by
    a sibling worker). Raises whatever `start_or_attach_server` raises if the
    restart itself fails — a half-restarted runtime must not look like success.
    """
    from ..deps import (
        get_opencode_client,
        get_opencode_handle,
        get_opencode_password,
        set_opencode,
    )

    write_opencode_config(data_dir, cfg, file_write_allowed=file_write_allowed)

    try:
        handle = get_opencode_handle()
        old_client = get_opencode_client()
        password = get_opencode_password()
    except RuntimeError:
        return False  # runtime not initialised (tests, or startup not finished)

    if not handle.owned:
        return False  # attached to a sibling worker's process — not ours to kill

    await old_client.close()
    await stop_server(handle)

    # flock is held per open file description: a second LOCK_EX on a new fd
    # would conflict with our own stale one, even inside the same process.
    if handle.lock_fd is not None:
        os.close(handle.lock_fd)
        handle.lock_fd = None

    new_handle = await start_or_attach_server(
        binary=binary_path(data_dir),
        config_dir=data_dir,
        log_path=data_dir / "opencode.log",
        lock_path=data_dir / "runtime.lock",
        port=cfg.opencode_port,
        password=password,
    )
    new_client = OpencodeClient(
        f"http://127.0.0.1:{new_handle.port}",
        password=password,
    )
    set_opencode(new_handle, new_client)
    return True


__all__ = ["apply_config_to_runtime"]
