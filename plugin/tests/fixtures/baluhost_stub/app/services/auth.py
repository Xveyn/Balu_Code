"""BaluHost stub: app.services.auth."""
from __future__ import annotations

from types import SimpleNamespace


def decode_token(token: str) -> SimpleNamespace:
    return SimpleNamespace(sub=1)
