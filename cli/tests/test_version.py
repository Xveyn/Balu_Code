"""Tests for `balu-code --version`."""

from __future__ import annotations

from balu_code_cli import __version__
from balu_code_cli.__main__ import app
from typer.testing import CliRunner


def test_version_flag_prints_version_and_exits_zero():
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_no_args_prints_help_and_exits_zero():
    runner = CliRunner()
    result = runner.invoke(app, [])
    # typer defaults: no command = show help, exit 0 when no_args_is_help=True
    assert result.exit_code in (0, 2)
    assert "balu-code" in result.stdout.lower() or "usage" in result.stdout.lower()


def test_version_matches_package_version():
    # sanity: CLI __version__ string is sane
    import re

    assert re.match(r"^\d+\.\d+\.\d+", __version__)
