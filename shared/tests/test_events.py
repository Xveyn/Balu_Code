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


class TestToolCall:
    def test_constructs_with_all_fields(self):
        from balu_code_shared.events import ToolCall

        evt = ToolCall(
            tool_call_id="tc_01",
            tool="read_file",
            args={"path": "foo.py"},
            auto_approved=True,
        )
        assert evt.type == "tool_call"
        assert evt.tool_call_id == "tc_01"
        assert evt.tool == "read_file"
        assert evt.args == {"path": "foo.py"}
        assert evt.auto_approved is True

    def test_rejects_empty_tool_call_id(self):
        import pytest
        from balu_code_shared.events import ToolCall
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ToolCall(tool_call_id="", tool="t", args={}, auto_approved=True)


class TestToolResult:
    def test_constructs_with_all_fields(self):
        from balu_code_shared.events import ToolResult

        evt = ToolResult(
            tool_call_id="tc_01",
            status="ok",
            bytes_out=42,
        )
        assert evt.type == "tool_result"
        assert evt.tool_call_id == "tc_01"
        assert evt.status == "ok"
        assert evt.bytes_out == 42
        assert evt.error is None

    def test_rejects_unknown_status(self):
        import pytest
        from balu_code_shared.events import ToolResult
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ToolResult(tool_call_id="tc_01", status="pending", bytes_out=0)

    def test_error_carries_message(self):
        from balu_code_shared.events import ToolResult

        evt = ToolResult(
            tool_call_id="tc_01",
            status="error",
            bytes_out=0,
            error="path escapes project root",
        )
        assert evt.status == "error"
        assert evt.error == "path escapes project root"


class TestParseFrameExtended:
    def test_parses_tool_call(self):
        from balu_code_shared.events import ToolCall, parse_frame

        evt = parse_frame(
            {
                "type": "tool_call",
                "tool_call_id": "tc_1",
                "tool": "glob",
                "args": {"pattern": "**/*.py"},
                "auto_approved": True,
            }
        )
        assert isinstance(evt, ToolCall)

    def test_parses_tool_result(self):
        from balu_code_shared.events import ToolResult, parse_frame

        evt = parse_frame(
            {
                "type": "tool_result",
                "tool_call_id": "tc_1",
                "status": "ok",
                "bytes_out": 10,
            }
        )
        assert isinstance(evt, ToolResult)


class TestApprovalRequest:
    def test_constructs_with_all_fields(self):
        from balu_code_shared.events import ApprovalRequest

        evt = ApprovalRequest(
            tool_call_id="tc_1",
            tool="write_file",
            args={"path": "foo.py", "content": "x"},
            risk="write",
        )
        assert evt.type == "approval_request"
        assert evt.tool_call_id == "tc_1"
        assert evt.tool == "write_file"
        assert evt.args == {"path": "foo.py", "content": "x"}
        assert evt.risk == "write"

    def test_rejects_empty_tool_call_id(self):
        import pytest
        from balu_code_shared.events import ApprovalRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ApprovalRequest(tool_call_id="", tool="t", args={}, risk="write")

    def test_rejects_unknown_risk(self):
        import pytest
        from balu_code_shared.events import ApprovalRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ApprovalRequest(tool_call_id="tc_1", tool="t", args={}, risk="read")


class TestApproval:
    def test_approved_true(self):
        from balu_code_shared.events import Approval

        evt = Approval(tool_call_id="tc_1", approved=True)
        assert evt.type == "approval"
        assert evt.approved is True
        assert evt.reason is None

    def test_approved_false_with_reason(self):
        from balu_code_shared.events import Approval

        evt = Approval(
            tool_call_id="tc_1",
            approved=False,
            reason="user said no",
        )
        assert evt.approved is False
        assert evt.reason == "user said no"

    def test_rejects_empty_tool_call_id(self):
        import pytest
        from balu_code_shared.events import Approval
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Approval(tool_call_id="", approved=True)


class TestCancel:
    def test_constructs_with_turn_id(self):
        from balu_code_shared.events import Cancel

        evt = Cancel(turn_id="t_1")
        assert evt.type == "cancel"
        assert evt.turn_id == "t_1"

    def test_rejects_empty_turn_id(self):
        import pytest
        from balu_code_shared.events import Cancel
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Cancel(turn_id="")


class TestStopReasonMaxTokens:
    def test_max_tokens_is_valid(self):
        evt = TurnEnd(
            turn_id="t_1",
            total_tokens=100,
            iterations=2,
            stop_reason="max_tokens",
        )
        assert evt.stop_reason == "max_tokens"


class TestParseFrameNewEvents:
    def test_parses_approval_request(self):
        from balu_code_shared.events import ApprovalRequest, parse_frame

        evt = parse_frame(
            {
                "type": "approval_request",
                "tool_call_id": "tc_1",
                "tool": "run_bash",
                "args": {"command": "ls"},
                "risk": "exec",
            }
        )
        assert isinstance(evt, ApprovalRequest)
        assert evt.risk == "exec"

    def test_parses_approval(self):
        from balu_code_shared.events import Approval, parse_frame

        evt = parse_frame(
            {"type": "approval", "tool_call_id": "tc_1", "approved": True}
        )
        assert isinstance(evt, Approval)

    def test_parses_cancel(self):
        from balu_code_shared.events import Cancel, parse_frame

        evt = parse_frame({"type": "cancel", "turn_id": "t_1"})
        assert isinstance(evt, Cancel)


def test_event_union_includes_all_ten():
    import typing

    annotated_args = typing.get_args(Event)
    union_type = annotated_args[0]
    members = typing.get_args(union_type)
    names = {m.model_fields["type"].default for m in members}
    assert names == {
        "user_message",
        "turn_start",
        "token",
        "turn_end",
        "error",
        "tool_call",
        "tool_result",
        "approval_request",
        "approval",
        "cancel",
    }
