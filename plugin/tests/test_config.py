"""Tests for BaluCodePluginConfig."""

from __future__ import annotations

from plugin.config import BaluCodePluginConfig


def test_defaults_are_populated():
    c = BaluCodePluginConfig()
    assert c.ollama_base_url == "http://127.0.0.1:11434"
    assert c.chat_model == "qwen2.5-coder:14b-instruct-q4_K_M"
    assert c.embed_model == "nomic-embed-text"


def test_model_dump_round_trip():
    original = BaluCodePluginConfig(
        ollama_base_url="http://10.0.0.5:11434",
        chat_model="qwen2.5-coder:7b",
        embed_model="nomic-embed-text",
    )
    data = original.model_dump()
    restored = BaluCodePluginConfig.model_validate(data)
    assert restored == original


def test_rejects_unknown_fields():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BaluCodePluginConfig.model_validate({"ollama_base_url": "http://x", "unknown": 1})
