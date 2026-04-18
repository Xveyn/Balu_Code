"""Stub of BaluHost's app.schemas.user. Minimal surface used by balu_code."""
from __future__ import annotations

from pydantic import BaseModel


class UserPublic(BaseModel):
    id: int = 1
    username: str = "testuser"
    email: str = "test@example.com"
    role: str = "admin"
    is_active: bool = True
