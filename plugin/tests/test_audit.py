"""Tests for AuditLogger wrapper."""

from __future__ import annotations

from typing import Any

import pytest

from plugin.services.audit import AuditLogger


class _FakeDBLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def log_event(
        self,
        *,
        event_type,
        user,
        action,
        resource=None,
        details=None,
        success=True,
        error_message=None,
        ip_address=None,
        user_agent=None,
        db=None,
    ):
        self.calls.append(
            {
                "event_type": event_type,
                "user": user,
                "action": action,
                "resource": resource,
                "details": details,
                "success": success,
                "error_message": error_message,
            }
        )
        return object()


@pytest.mark.asyncio
async def test_records_ok_tool_call_as_balu_code_event() -> None:
    fake = _FakeDBLogger()
    logger = AuditLogger(fake)
    await logger.record_tool_call(
        tool="write_file",
        user="sven",
        turn_id="t_1",
        tool_call_id="tc_1",
        args={"path": "foo.py", "content": "x"},
        status="ok",
        bytes_out=1,
        error=None,
        approved=True,
        auto_approved=False,
    )
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["event_type"] == "BALU_CODE"
    assert call["user"] == "sven"
    assert call["action"] == "tool:write_file"
    assert call["resource"] == "foo.py"
    assert call["success"] is True
    assert call["details"]["turn_id"] == "t_1"
    assert call["details"]["approved"] is True
    assert call["details"]["auto_approved"] is False


@pytest.mark.asyncio
async def test_records_error_and_rejection() -> None:
    fake = _FakeDBLogger()
    logger = AuditLogger(fake)
    await logger.record_tool_call(
        tool="run_bash",
        user="sven",
        turn_id="t_1",
        tool_call_id="tc_2",
        args={"command": "rm -rf /"},
        status="error",
        bytes_out=0,
        error="user rejected: no",
        approved=False,
        auto_approved=False,
    )
    call = fake.calls[0]
    assert call["success"] is False
    assert call["error_message"] == "user rejected: no"
    assert call["resource"] == "rm -rf /"
    assert call["details"]["approved"] is False


@pytest.mark.asyncio
async def test_resource_slot_uses_most_identifying_arg() -> None:
    fake = _FakeDBLogger()
    logger = AuditLogger(fake)
    await logger.record_tool_call(
        tool="web_fetch",
        user="sven",
        turn_id="t_1",
        tool_call_id="tc_3",
        args={"url": "https://example.com/x"},
        status="ok",
        bytes_out=100,
        error=None,
        approved=True,
        auto_approved=True,
    )
    assert fake.calls[0]["resource"] == "https://example.com/x"


@pytest.mark.asyncio
async def test_resource_slot_falls_back_to_tool_name() -> None:
    fake = _FakeDBLogger()
    logger = AuditLogger(fake)
    await logger.record_tool_call(
        tool="grep",
        user="sven",
        turn_id="t_1",
        tool_call_id="tc_4",
        args={"pattern": "TODO"},
        status="ok",
        bytes_out=42,
        error=None,
        approved=True,
        auto_approved=True,
    )
    # pattern is in the priority list -> resource = "TODO"
    assert fake.calls[0]["resource"] == "TODO"


@pytest.mark.asyncio
async def test_resource_truncates_long_values() -> None:
    fake = _FakeDBLogger()
    logger = AuditLogger(fake)
    long_cmd = "echo " + "x" * 500
    await logger.record_tool_call(
        tool="run_bash",
        user="sven",
        turn_id="t_1",
        tool_call_id="tc_5",
        args={"command": long_cmd},
        status="ok",
        bytes_out=0,
        error=None,
        approved=True,
        auto_approved=False,
    )
    assert len(fake.calls[0]["resource"]) <= 200
