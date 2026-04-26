"""Tests for commands/config.py."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from balu_code_cli.commands.config import app
from balu_code_cli.config.loader import AppConfig, save_config

runner = CliRunner()


def test_config_get_server_url():
    with patch("balu_code_cli.commands.config.load_config",
               return_value=AppConfig(server_url="https://example.com")):
        result = runner.invoke(app, ["get", "server_url"])
    assert result.exit_code == 0
    assert "https://example.com" in result.output


def test_config_get_unknown_key():
    result = runner.invoke(app, ["get", "nonexistent_key"])
    assert result.exit_code != 0
    assert "Unknown key" in result.output
    assert "server_url" in result.output


def test_config_set_default_project_id():
    saved = {}

    def fake_save(cfg, path=None):
        saved["cfg"] = cfg

    with patch("balu_code_cli.commands.config.load_config", return_value=AppConfig()), \
         patch("balu_code_cli.commands.config.save_config", side_effect=fake_save):
        result = runner.invoke(app, ["set", "default_project_id", "7"])
    assert result.exit_code == 0
    assert saved["cfg"].default_project_id == 7


def test_config_set_server_url():
    saved = {}

    def fake_save(cfg, path=None):
        saved["cfg"] = cfg

    with patch("balu_code_cli.commands.config.load_config", return_value=AppConfig()), \
         patch("balu_code_cli.commands.config.save_config", side_effect=fake_save):
        result = runner.invoke(app, ["set", "server_url", "https://new.example.com"])
    assert result.exit_code == 0
    assert saved["cfg"].server_url == "https://new.example.com"


def test_config_set_type_error_for_project_id():
    with patch("balu_code_cli.commands.config.load_config", return_value=AppConfig()):
        result = runner.invoke(app, ["set", "default_project_id", "notanumber"])
    assert result.exit_code != 0
    assert "integer" in result.output.lower()


def test_config_set_unknown_key():
    result = runner.invoke(app, ["set", "nonexistent_key", "value"])
    assert result.exit_code != 0
    assert "Unknown key" in result.output
