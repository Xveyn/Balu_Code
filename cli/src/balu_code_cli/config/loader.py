"""AppConfig + Credentials read/write."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel

from balu_code_cli.config.paths import config_yaml, credentials_yaml


class AppConfig(BaseModel):
    server_url: str = ""
    default_project_id: int | None = None


class ServerCredentials(BaseModel):
    api_key: str


class Credentials(BaseModel):
    servers: dict[str, ServerCredentials] = {}


def load_config(path: Path | None = None) -> AppConfig:
    p = path or config_yaml()
    if not p.exists():
        return AppConfig()
    data = yaml.safe_load(p.read_text()) or {}
    return AppConfig.model_validate(data)


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    p = path or config_yaml()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(cfg.model_dump(exclude_none=True)))


def load_credentials(path: Path | None = None) -> Credentials:
    p = path or credentials_yaml()
    if not p.exists():
        return Credentials()
    data = yaml.safe_load(p.read_text()) or {}
    return Credentials.model_validate(data)


def save_credentials(creds: Credentials, path: Path | None = None) -> None:
    p = path or credentials_yaml()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(creds.model_dump()))
    os.chmod(p, 0o600)


__all__ = [
    "AppConfig",
    "Credentials",
    "ServerCredentials",
    "load_config",
    "load_credentials",
    "save_config",
    "save_credentials",
]
