"""Pure mapping from BaluCodePluginConfig to opencode.json.

Key names match opencode's Config schema (see docs/superpowers/references/
opencode-openapi.json, /config GET response). opencode reads its config from
`<OPENCODE_CONFIG_DIR>/opencode.json` (env var set at server spawn).

For v0.2.0 we map only the fields Sven actually uses:
- BaluCodePluginConfig.ollama_base_url → provider.ollama.options.baseURL
- BaluCodePluginConfig.chat_model → model (formatted "ollama/<id>")
- file_write_allowed=False → permission.{edit, bash} = "deny"

Other opencode config keys (lsp, formatter, agents, mcp, …) are intentionally
omitted; opencode will fall back to its own defaults.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import BaluCodePluginConfig


def to_opencode_config(
    cfg: BaluCodePluginConfig,
    *,
    file_write_allowed: bool,
) -> dict:
    """Build an opencode.json dict from plugin config + permission state.

    opencode wires up custom providers via the AI SDK ecosystem: each
    provider block needs `npm` (the npm package that implements it),
    `name`, `options` (passed verbatim to the SDK constructor), and a
    `models` dict listing the models we expose. For Ollama we use
    `ollama-ai-provider-v2`. Without these fields opencode silently
    drops the provider — only opencode's default model surface remains.
    """
    base_url = cfg.ollama_base_url.rstrip("/")
    if not base_url.endswith("/api"):
        base_url = f"{base_url}/api"

    out: dict = {
        "model": f"ollama/{cfg.chat_model}",
        "provider": {
            "ollama": {
                "npm": "ollama-ai-provider-v2",
                "name": "Ollama (local)",
                "options": {"baseURL": base_url},
                "models": {
                    cfg.chat_model: {"name": cfg.chat_model},
                },
            },
        },
    }
    if not file_write_allowed:
        out["permission"] = {"edit": "deny", "bash": "deny"}
    return out


def write_opencode_config(
    data_dir: Path,
    cfg: BaluCodePluginConfig,
    *,
    file_write_allowed: bool,
) -> Path:
    """Write the generated config to <data_dir>/opencode.json. Returns path."""
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "opencode.json"
    payload = to_opencode_config(cfg, file_write_allowed=file_write_allowed)
    out_path.write_text(json.dumps(payload, indent=2))
    return out_path


__all__ = ["to_opencode_config", "write_opencode_config"]
