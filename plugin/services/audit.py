"""Audit-log adapter — wraps BaluHost's AuditLoggerDB for tool calls.

``AuditLoggerDB.log_event`` is synchronous and DB-backed. This wrapper
shapes a tool-call record into that method's contract and dispatches it
on a worker thread so the async agent loop never blocks on DB I/O.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

_EVENT_TYPE = "BALU_CODE"
_RESOURCE_MAX = 200


class _DBLoggerProto(Protocol):
    def log_event(
        self,
        *,
        event_type: str,
        user: str | None,
        action: str,
        resource: str | None = None,
        details: dict | None = None,
        success: bool = True,
        error_message: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        db: Any = None,
    ) -> Any: ...


class AuditLogger:
    def __init__(self, db_logger: _DBLoggerProto) -> None:
        self._db = db_logger

    async def record_tool_call(
        self,
        *,
        tool: str,
        user: str,
        turn_id: str,
        tool_call_id: str,
        args: dict,
        status: str,
        bytes_out: int,
        error: str | None,
        approved: bool,
        auto_approved: bool,
    ) -> None:
        resource = _derive_resource(tool, args)
        details = {
            "turn_id": turn_id,
            "tool_call_id": tool_call_id,
            "args": args,
            "bytes_out": bytes_out,
            "approved": approved,
            "auto_approved": auto_approved,
        }
        success = status == "ok"
        await asyncio.to_thread(
            self._db.log_event,
            event_type=_EVENT_TYPE,
            user=user,
            action=f"tool:{tool}",
            resource=resource,
            details=details,
            success=success,
            error_message=error,
        )


def _derive_resource(tool: str, args: dict) -> str:
    for key in ("path", "url", "command", "pattern"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value[:_RESOURCE_MAX]
    return tool[:_RESOURCE_MAX]


__all__ = ["AuditLogger"]
