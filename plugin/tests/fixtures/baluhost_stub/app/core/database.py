"""BaluHost stub: app.core.database."""
from __future__ import annotations

from typing import Generator


class _NoopDB:
    pass


def get_db() -> Generator[_NoopDB, None, None]:
    yield _NoopDB()
