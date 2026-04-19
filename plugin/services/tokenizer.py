"""Token counting via tiktoken's cl100k_base encoder.

The encoder is a reasonable default for the models we target
(qwen2.5-coder, llama3.1+, mistral-large, deepseek-coder). Expect
~10-15 percent error against the model's native tokenizer; the
agent loop carries a safety margin (``max_total_tokens_per_turn``)
that absorbs the drift.
"""

from __future__ import annotations

import json
from functools import lru_cache

import tiktoken

_MESSAGE_OVERHEAD = 4  # approximate fixed cost for role+content framing


@lru_cache(maxsize=1)
def _get_encoder() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_get_encoder().encode(text))


def count_messages_tokens(messages: list[dict]) -> int:
    if not messages:
        return 0
    total = 0
    for msg in messages:
        total += _MESSAGE_OVERHEAD
        content = msg.get("content") or ""
        if content:
            total += count_tokens(content)
        tool_calls = msg.get("tool_calls") or []
        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments")
            args_str = args if isinstance(args, str) else json.dumps(args or {})
            total += count_tokens(name) + count_tokens(args_str)
    return total


__all__ = ["count_messages_tokens", "count_tokens"]
