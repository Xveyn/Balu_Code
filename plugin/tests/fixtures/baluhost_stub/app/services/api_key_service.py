"""BaluHost stub: app.services.api_key_service."""
from __future__ import annotations

from types import SimpleNamespace


class ApiKeyService:
    @staticmethod
    def validate_api_key(db, token: str) -> SimpleNamespace | None:
        return None
