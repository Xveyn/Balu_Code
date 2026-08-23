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
    repo_map_enabled: bool = True
    repo_map_budget: int = 2048
    rag_budget: int = 4096
    rag_top_k: int = 8
    max_iterations: int = 12
    max_total_tokens_per_turn: int = 80000
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    poll_interval_seconds: int = Field(default=10, ge=3, le=300)

    # Reasoning-trace control for thinking-capable models (qwen3.8 and friends),
    # forwarded to opencode as providerOptions.ollama.think. Three-valued on
    # purpose, because both extremes are traps:
    #   None  -> key omitted. Ollama then enables thinking for every model that
    #            advertises the capability, i.e. qwen3.8 runs its longest trace.
    #   False -> trace off. Measured on the reference box (RX 7900 XT,
    #            qwen3.8:27b q4_K_M): the same coding task cost 2493 output
    #            tokens / 65.8s with the trace and 1096 / 27.7s without.
    #   True  -> trace on, explicitly.
    # Not defaulted to False: models without the thinking capability can reject
    # a request that carries the field at all, and the default chat_model is one
    # of them. Set it per install once a thinking-capable model is selected.
    think: bool | None = None

    # Phase A opencode integration
    opencode_port: int = Field(default=4096, ge=0, le=65535)


__all__ = ["BaluCodePluginConfig"]
