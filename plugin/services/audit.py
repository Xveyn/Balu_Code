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

    async def query_recent_tool_calls(self, limit: int = 100) -> list[dict]:
        return await asyncio.to_thread(self._query_sync, limit)

    async def record_turn_end(
        self,
        *,
        turn_id: str,
        model: str,
        username: str,
        prompt_eval_count: int,
        eval_count: int,
        eval_duration_ns: int,
        total_duration_ms: int,
        iterations: int,
    ) -> None:
        tokens_per_s = (
            round(eval_count / (eval_duration_ns / 1e9), 2)
            if eval_duration_ns > 0
            else 0.0
        )
        details = {
            "turn_id": turn_id,
            "model": model,
            "prompt_eval_count": prompt_eval_count,
            "eval_count": eval_count,
            "tokens_per_s": tokens_per_s,
            "total_duration_ms": total_duration_ms,
            "iterations": iterations,
        }
        await asyncio.to_thread(
            self._db.log_event,
            event_type=_EVENT_TYPE,
            user=username,
            action="turn:end",
            resource=model,
            details=details,
            success=True,
            error_message=None,
        )

    async def query_stats(self, days: int = 7) -> dict:
        return await asyncio.to_thread(self._query_stats_sync, days)

    def _query_stats_sync(self, days: int) -> dict:
        import json as _json
        from datetime import UTC, datetime, timedelta

        from app.core.database import SessionLocal
        from app.models.audit_log import AuditLog as DBLog

        since = datetime.now(UTC) - timedelta(days=days)

        with SessionLocal() as db:
            if db is None:
                return _empty_stats(days)

            turn_rows = (
                db.query(DBLog)
                .filter(DBLog.event_type == "BALU_CODE", DBLog.action == "turn:end")
                .filter(DBLog.timestamp >= since)
                .order_by(DBLog.timestamp.asc())
                .all()
            )
            tool_rows = (
                db.query(DBLog)
                .filter(DBLog.event_type == "BALU_CODE", DBLog.action.like("tool:%"))
                .filter(DBLog.timestamp >= since)
                .all()
            )

        days_map: dict[str, dict] = {}
        for i in range(days):
            d = (datetime.now(UTC) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
            days_map[d] = {"date": d, "requests": 0, "tokens_in": 0, "tokens_out": 0}

        by_model: dict[str, dict] = {}
        for row in turn_rows:
            det = _json.loads(row.details) if row.details else {}
            d = row.timestamp.strftime("%Y-%m-%d")
            if d in days_map:
                days_map[d]["requests"] += 1
                days_map[d]["tokens_in"] += det.get("prompt_eval_count", 0)
                days_map[d]["tokens_out"] += det.get("eval_count", 0)
            m = det.get("model", "unknown")
            if m not in by_model:
                by_model[m] = {"model": m, "requests": 0, "_tps_sum": 0.0}
            by_model[m]["requests"] += 1
            by_model[m]["_tps_sum"] += det.get("tokens_per_s", 0.0)

        by_model_list = [
            {
                "model": v["model"],
                "requests": v["requests"],
                "avg_tokens_per_s": round(v["_tps_sum"] / v["requests"], 2)
                if v["requests"] > 0 else 0.0,
            }
            for v in by_model.values()
        ]

        tool_counts: dict[str, dict] = {}
        auto_approved = user_approved = rejected = 0
        for row in tool_rows:
            det = _json.loads(row.details) if row.details else {}
            name = row.action.removeprefix("tool:")
            if name not in tool_counts:
                tool_counts[name] = {"tool": name, "calls": 0, "_ok": 0}
            tool_counts[name]["calls"] += 1
            if row.success:
                tool_counts[name]["_ok"] += 1
            if det.get("auto_approved"):
                auto_approved += 1
            elif det.get("approved"):
                user_approved += 1
            else:
                rejected += 1

        top_tools = sorted(
            [
                {
                    "tool": v["tool"],
                    "calls": v["calls"],
                    "success_rate": round(v["_ok"] / v["calls"], 2)
                    if v["calls"] > 0 else 0.0,
                }
                for v in tool_counts.values()
            ],
            key=lambda x: x["calls"],
            reverse=True,
        )[:10]

        return {
            "last_n_days": list(days_map.values()),
            "by_model": by_model_list,
            "top_tools": top_tools,
            "approval_summary": {
                "auto_approved": auto_approved,
                "user_approved": user_approved,
                "rejected": rejected,
            },
        }

    def _query_sync(self, limit: int) -> list[dict]:
        import json as _json

        from app.core.database import SessionLocal
        from app.models.audit_log import AuditLog as DBLog

        with SessionLocal() as db:
            if db is None:
                return []
            rows = (
                db.query(DBLog)
                .filter(DBLog.event_type == "BALU_CODE")
                .order_by(DBLog.timestamp.desc())
                .limit(limit)
                .all()
            )
            result = []
            for r in rows:
                details = _json.loads(r.details) if r.details else {}
                result.append(
                    {
                        "id": r.id,
                        "timestamp": r.timestamp.isoformat(),
                        "user": r.user,
                        "action": r.action,
                        "resource": r.resource,
                        "success": r.success,
                        "error_message": r.error_message,
                        "turn_id": details.get("turn_id"),
                        "tool_call_id": details.get("tool_call_id"),
                    }
                )
            return result


def _derive_resource(tool: str, args: dict) -> str:
    for key in ("path", "url", "command", "pattern"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value[:_RESOURCE_MAX]
    return tool[:_RESOURCE_MAX]


def _empty_stats(days: int) -> dict:
    from datetime import UTC, datetime, timedelta

    return {
        "last_n_days": [
            {
                "date": (datetime.now(UTC) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d"),
                "requests": 0,
                "tokens_in": 0,
                "tokens_out": 0,
            }
            for i in range(days)
        ],
        "by_model": [],
        "top_tools": [],
        "approval_summary": {"auto_approved": 0, "user_approved": 0, "rejected": 0},
    }


__all__ = ["AuditLogger"]
