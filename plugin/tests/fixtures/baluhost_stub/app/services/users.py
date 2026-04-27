"""BaluHost stub: app.services.users."""
from __future__ import annotations

from app.schemas.user import UserPublic


def get_user(user_id: int, db=None) -> UserPublic:
    return UserPublic(id=user_id)


def serialize_user(user: UserPublic) -> UserPublic:
    return user
