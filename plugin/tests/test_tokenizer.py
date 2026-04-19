"""Tests for tokenizer helpers."""

from __future__ import annotations

from plugin.services.tokenizer import count_messages_tokens, count_tokens


def test_count_tokens_empty_string_is_zero():
    assert count_tokens("") == 0


def test_count_tokens_hello_world_is_positive():
    assert count_tokens("hello world") > 0


def test_count_tokens_longer_text_is_larger():
    short = count_tokens("hi")
    long = count_tokens("this is a substantially longer sentence with many tokens")
    assert long > short


def test_count_messages_tokens_sums_content():
    messages = [
        {"role": "system", "content": "you are a helpful assistant"},
        {"role": "user", "content": "hello"},
    ]
    total = count_messages_tokens(messages)
    sys_only = count_tokens("you are a helpful assistant")
    user_only = count_tokens("hello")
    assert total > sys_only + user_only


def test_count_messages_tokens_empty_list_is_zero():
    assert count_messages_tokens([]) == 0


def test_count_messages_tokens_handles_tool_calls():
    messages = [
        {
            "role": "assistant",
            "content": "calling a tool",
            "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "a.py"}}}],
        }
    ]
    total = count_messages_tokens(messages)
    content_only = count_messages_tokens([{"role": "assistant", "content": "calling a tool"}])
    assert total > content_only
