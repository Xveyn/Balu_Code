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


def test_defaults_for_phase_4a_fields():
    c = BaluCodePluginConfig()
    assert c.context_window == 32768
    assert c.repo_map_budget == 6144
    assert c.rag_budget == 4096
    assert c.rag_top_k == 8
    assert c.max_iterations == 12
    assert c.max_total_tokens_per_turn == 80000
    assert c.temperature == 0.2


def test_temperature_rejects_out_of_range():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BaluCodePluginConfig(temperature=-0.1)
    with pytest.raises(ValidationError):
        BaluCodePluginConfig(temperature=2.5)


def test_poll_interval_seconds_default():
    cfg = BaluCodePluginConfig()
    assert cfg.poll_interval_seconds == 10


def test_poll_interval_seconds_min_enforced():
    import pytest

    with pytest.raises(Exception):
        BaluCodePluginConfig(poll_interval_seconds=2)


def test_config_update_request_accepts_poll_interval():
    from plugin.schemas import ConfigUpdateRequest
    req = ConfigUpdateRequest(poll_interval_seconds=5)
    assert req.poll_interval_seconds == 5


def test_config_update_request_rejects_poll_interval_below_3():
    import pytest
    from plugin.schemas import ConfigUpdateRequest

    with pytest.raises(Exception):
        ConfigUpdateRequest(poll_interval_seconds=2)
