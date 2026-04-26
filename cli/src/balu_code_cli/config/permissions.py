"""PermissionsStore — per server+project+tool approval decisions."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from balu_code_cli.config.paths import permissions_yaml


class PermissionsStore(BaseModel):
    permissions: dict[str, dict[str, dict[str, bool]]] = {}

    def lookup(self, server_url: str, project_id: int, tool_name: str) -> bool | None:
        return self.permissions.get(server_url, {}).get(str(project_id), {}).get(tool_name)

    def set(self, server_url: str, project_id: int, tool_name: str, approved: bool) -> None:
        (self.permissions.setdefault(server_url, {}).setdefault(str(project_id), {}))[tool_name] = (
            approved
        )


def load_permissions(path: Path | None = None) -> PermissionsStore:
    p = path or permissions_yaml()
    if not p.exists():
        return PermissionsStore()
    try:
        data = yaml.safe_load(p.read_text()) or {}
        return PermissionsStore.model_validate(data)
    except Exception:
        return PermissionsStore()


def save_permissions(store: PermissionsStore, path: Path | None = None) -> None:
    p = path or permissions_yaml()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(store.model_dump()))


__all__ = ["PermissionsStore", "load_permissions", "save_permissions"]
