"""Plugin-global configuration for balu_code (Phase 2 subset).

Returned by ``BaluCodePlugin.get_config_schema()`` and used by
``BaluCodePlugin.on_startup()`` to construct the OllamaClient and to
report the default chat/embed model when BaluHost serves no per-install
override. Later phases extend this model with RAG/context/iteration
settings.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BaluCodePluginConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ollama_base_url: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen2.5-coder:14b"
    embed_model: str = "nomic-embed-text"

    # Phase 4a agent-loop knobs
    context_window: int = 32768
    repo_map_budget: int = 6144
    rag_budget: int = 4096
    rag_top_k: int = 8
    max_iterations: int = 12
    max_total_tokens_per_turn: int = 80000
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


__all__ = ["BaluCodePluginConfig"]
