from __future__ import annotations

from typing import Any
from unittest.mock import patch

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
        **kw,
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


@pytest.mark.asyncio
async def test_record_turn_end_logs_turn_end_action():
    db = _FakeDBLogger()
    audit = AuditLogger(db)
    await audit.record_turn_end(
        turn_id="t1",
        model="qwen2.5-coder:14b",
        username="sven",
        prompt_eval_count=1000,
        eval_count=400,
        eval_duration_ns=22_000_000_000,
        total_duration_ms=25000,
        iterations=3,
    )
    assert len(db.calls) == 1
    call = db.calls[0]
    assert call["action"] == "turn:end"
    assert call["resource"] == "qwen2.5-coder:14b"
    assert call["user"] == "sven"
    details = call["details"]
    assert details["turn_id"] == "t1"
    assert details["eval_count"] == 400
    assert details["prompt_eval_count"] == 1000
    assert details["iterations"] == 3
    assert details["tokens_per_s"] > 0


@pytest.mark.asyncio
async def test_record_turn_end_zero_duration_does_not_divide_by_zero():
    db = _FakeDBLogger()
    audit = AuditLogger(db)
    await audit.record_turn_end(
        turn_id="t2",
        model="qwen2.5-coder:14b",
        username="sven",
        prompt_eval_count=0,
        eval_count=0,
        eval_duration_ns=0,
        total_duration_ms=0,
        iterations=1,
    )
    details = db.calls[0]["details"]
    assert details["tokens_per_s"] == 0.0


@pytest.mark.asyncio
async def test_query_stats_returns_expected_shape():
    db = _FakeDBLogger()
    audit = AuditLogger(db)
    with patch.object(
        audit,
        "_query_stats_sync",
        return_value={
            "last_n_days": [
                {"date": "2026-04-26", "requests": 5, "tokens_in": 10000, "tokens_out": 2000}
            ],
            "by_model": [{"model": "qwen2.5-coder:14b", "requests": 5, "avg_tokens_per_s": 18.5}],
            "top_tools": [{"tool": "read_file", "calls": 20, "success_rate": 0.95}],
            "approval_summary": {"auto_approved": 15, "user_approved": 3, "rejected": 1},
        },
    ):
        result = await audit.query_stats(days=7)
    assert "last_n_days" in result
    assert "by_model" in result
    assert "top_tools" in result
    assert "approval_summary" in result
    assert result["approval_summary"]["auto_approved"] == 15
