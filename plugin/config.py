"""Plugin-global configuration for balu_code (Phase 2 subset).

Returned by ``BaluCodePlugin.get_config_schema()`` and used by
``BaluCodePlugin.on_startup()`` to construct the OllamaClient and to
report the default chat/embed model when BaluHost serves no per-install
override. Later phases extend this model with RAG/context/iteration
settings.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaluCodePluginConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ollama_base_url: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen2.5-coder:14b-instruct-q4_K_M"
    embed_model: str = "nomic-embed-text"


__all__ = ["BaluCodePluginConfig"]
