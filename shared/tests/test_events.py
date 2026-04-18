"""Tests for balu_code_shared.events."""

from __future__ import annotations

import pytest
from balu_code_shared.events import (
    Error,
    Event,
    Token,
    TurnEnd,
    TurnStart,
    UserMessage,
    parse_frame,
)
from pydantic import ValidationError


class TestUserMessage:
    def test_constructs_with_content(self):
        msg = UserMessage(content="hello")
        assert msg.type == "user_message"
        assert msg.content == "hello"

    def test_rejects_empty_content(self):
        with pytest.raises(ValidationError):
            UserMessage(content="")


class TestTurnStart:
    def test_constructs_with_required_fields(self):
        evt = TurnStart(turn_id="t_1", model="qwen2.5-coder:14b", context_tokens=9840)
        assert evt.type == "turn_start"
        assert evt.turn_id == "t_1"
        assert evt.model == "qwen2.5-coder:14b"
        assert evt.context_tokens == 9840

    def test_rejects_negative_context_tokens(self):
        with pytest.raises(ValidationError):
            TurnStart(turn_id="t_1", model="m", context_tokens=-1)


class TestToken:
    def test_constructs_with_content(self):
        evt = Token(content="hello ")
        assert evt.type == "token"
        assert evt.content == "hello "

    def test_allows_empty_token_string(self):
        evt = Token(content="")
        assert evt.content == ""


class TestTurnEnd:
    def test_constructs_with_all_fields(self):
        evt = TurnEnd(
            turn_id="t_1",
            total_tokens=18432,
            iterations=3,
            stop_reason="done",
        )
        assert evt.type == "turn_end"
        assert evt.stop_reason == "done"

    def test_rejects_unknown_stop_reason(self):
        with pytest.raises(ValidationError):
            TurnEnd(
                turn_id="t_1",
                total_tokens=10,
                iterations=1,
                stop_reason="weird",
            )


class TestError:
    def test_constructs_with_code_and_message(self):
        evt = Error(code="ollama_unreachable", message="connection refused")
        assert evt.type == "error"
        assert evt.code == "ollama_unreachable"


class TestParseFrame:
    def test_parses_user_message(self):
        evt = parse_frame({"type": "user_message", "content": "hi"})
        assert isinstance(evt, UserMessage)
        assert evt.content == "hi"

    def test_parses_turn_start(self):
        evt = parse_frame(
            {"type": "turn_start", "turn_id": "t_1", "model": "m", "context_tokens": 42}
        )
        assert isinstance(evt, TurnStart)

    def test_rejects_unknown_type(self):
        with pytest.raises(ValidationError):
            parse_frame({"type": "mystery", "x": 1})

    def test_rejects_missing_type(self):
        with pytest.raises(ValidationError):
            parse_frame({"content": "no type field"})


def test_event_union_includes_all_five():
    import typing

    # Event is Annotated[Union[...], Field(discriminator=...)]; unwrap both layers.
    annotated_args = typing.get_args(Event)
    union_type = annotated_args[0]
    members = typing.get_args(union_type)
    names = {m.model_fields["type"].default for m in members}
    assert names == {"user_message", "turn_start", "token", "turn_end", "error"}
