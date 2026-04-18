"""Stub of BaluHost's app.api.deps. Returns a fixed admin user.

Tests that need a 401 path use FastAPI's ``app.dependency_overrides``
to swap ``get_current_user`` for one that raises ``HTTPException(401)``.
"""
from __future__ import annotations

from app.schemas.user import UserPublic


async def get_current_user() -> UserPublic:
    return UserPublic()
