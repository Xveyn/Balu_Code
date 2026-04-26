"""Release: bump versions, commit, tag, push.

Usage:
    python -m scripts.release --version 0.1.0
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PLUGIN_JSON = REPO_ROOT / "plugin" / "plugin.json"
CLI_PYPROJECT = REPO_ROOT / "cli" / "pyproject.toml"
CHANGELOG = REPO_ROOT / "docs" / "CHANGELOG.md"


def run(cmd: list[str], **kw) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, **kw)
    return result.stdout.strip()


def check_clean_tree() -> None:
    status = run(["git", "status", "--porcelain"])
    dirty = [ln for ln in status.splitlines() if not ln.startswith("??")]
    if dirty:
        print(f"Working tree is dirty:\n{status}", file=sys.stderr)
        sys.exit(1)


def bump_plugin_json(version: str) -> None:
    data = json.loads(PLUGIN_JSON.read_text())
    data["version"] = version
    PLUGIN_JSON.write_text(json.dumps(data, indent=2) + "\n")


def bump_pyproject(version: str) -> None:
    text = CLI_PYPROJECT.read_text()
    text = re.sub(r'^version = ".*"', f'version = "{version}"', text, flags=re.MULTILINE)
    CLI_PYPROJECT.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump version, commit, tag, push.")
    parser.add_argument("--version", required=True, help="Version string, e.g. 0.1.0 or v0.1.0")
    args = parser.parse_args()
    version = args.version.lstrip("v")

    check_clean_tree()
    bump_plugin_json(version)
    bump_pyproject(version)

    run(["git", "add", str(PLUGIN_JSON), str(CLI_PYPROJECT)])
    run(["git", "commit", "-m", f"chore(release): v{version}"])
    run(["git", "tag", f"v{version}"])
    run(["git", "push", "origin", "main", "--tags"])
    print(f"✓ Released v{version}")


if __name__ == "__main__":
    main()
