"""BaluHost stub: app.services.audit."""
from __future__ import annotations


class _NoopDBLogger:
    def log_event(self, **kwargs) -> None:
        pass


def get_audit_logger_db() -> _NoopDBLogger:
    return _NoopDBLogger()
