"""Stub of BaluHost's app.plugins.base for use in balu_code plugin tests.

Mirrors only the surface area balu_code imports. Keep in sync with
/opt/baluhost/backend/app/plugins/base.py when that file changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict, List, Optional

from pydantic import BaseModel, Field


class PluginMetadata(BaseModel):
    name: str
    version: str
    display_name: str
    description: str
    author: str
    required_permissions: List[str] = Field(default_factory=list)
    category: str = "general"
    homepage: Optional[str] = None
    min_baluhost_version: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)


@dataclass
class BackgroundTaskSpec:
    name: str
    func: Callable[[], Coroutine[Any, Any, None]]
    interval_seconds: float
    run_on_startup: bool = True


class PluginBase(ABC):
    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        ...

    def get_router(self):  # type: ignore[no-untyped-def]
        return None

    async def on_startup(self) -> None:
        return None

    async def on_shutdown(self) -> None:
        return None

    def get_background_tasks(self) -> List[BackgroundTaskSpec]:
        return []

    def get_config_schema(self) -> Optional[type]:
        return None

    def get_default_config(self) -> Dict[str, Any]:
        return {}
