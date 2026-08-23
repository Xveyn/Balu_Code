"""Behaviour tests for scripts/deploy-local.sh.

The paths worth testing are the ones that only surface on a real box: an owner
the machine does not know, a plugin that does not load, a service that must
never be left stopped. They run here against stubbed systemctl/curl/sudo/chown,
so a regression does not have to be discovered mid-deploy — which is exactly
how the missing owner detection was found the first time round.

Linux-only: the stubs rely on a POSIX PATH and the script targets the machine
BaluHost runs on.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_bhplugin import build_bhplugin

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "deploy-local.sh"

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="stubs a POSIX PATH; the script targets the Linux box BaluHost runs on",
)

_SYSTEMCTL_STUB = """#!/bin/sh
echo "systemctl $*" >> "$STUB_LOG"
case "$1" in
  cat) exit 0 ;;
  show)
    case "$*" in
      *"-p User"*) echo "$STUB_USER" ;;
      *"-p Group"*) echo "$STUB_GROUP" ;;
    esac
    exit 0 ;;
  stop) echo stopped > "$STUB_STATE"; exit 0 ;;
  start|restart) echo running > "$STUB_STATE"; exit 0 ;;
esac
exit 0
"""

_CURL_STUB = """#!/bin/sh
case "$*" in
  *"-o /dev/null"*) printf '%s' "$STUB_HTTP_CODE" ;;
  *) printf '{"status":"ok","plugin":"balu_code","version":"0.0.0"}' ;;
esac
exit 0
"""

_STUBS = {
    "sudo": '#!/bin/sh\nexec "$@"\n',
    "chown": "#!/bin/sh\nexit 0\n",
    "systemctl": _SYSTEMCTL_STUB,
    "curl": _CURL_STUB,
}


def _primary_group() -> str:
    # POSIX-only module: imported here, not at module scope, so collection
    # still works on a dev box that is not Linux.
    import grp

    return grp.getgrgid(os.getgid()).gr_name


@pytest.fixture
def env_and_state(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in _STUBS.items():
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)

    state = tmp_path / "service-state"
    state.write_text("running\n")
    log = tmp_path / "systemctl.log"
    log.write_text("")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["STUB_STATE"] = str(state)
    env["STUB_LOG"] = str(log)
    env["STUB_USER"] = getpass.getuser()
    env["STUB_GROUP"] = _primary_group()
    env["STUB_HTTP_CODE"] = "200"
    return env, state, log


@pytest.fixture
def install_root(tmp_path):
    root = tmp_path / "installed"
    (root / "balu_code").mkdir(parents=True)
    (root / "balu_code" / "marker.txt").write_text("previous\n")
    return root


@pytest.fixture
def backup_dir(tmp_path):
    """Backups must land outside the install root — BaluHost would otherwise
    discover them as additional plugins."""
    return tmp_path / "backups"


@pytest.fixture
def artefact(tmp_path):
    return build_bhplugin(REPO_ROOT, tmp_path / "dist")


def _run(env, install_root, backup_dir, *extra):
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--install-root",
            str(install_root),
            "--backup-dir",
            str(backup_dir),
            *extra,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_successful_deploy_installs_and_leaves_the_service_running(
    env_and_state, install_root, backup_dir, artefact
):
    env, state, _ = env_and_state

    result = _run(env, install_root, backup_dir, "--artefact", str(artefact))

    assert result.returncode == 0, result.stdout + result.stderr
    assert state.read_text().strip() == "running"
    target = install_root / "balu_code"
    assert (target / "plugin.json").exists()
    assert not (target / "marker.txt").exists(), "old install should have been replaced"
    assert list(backup_dir.glob("balu_code-*")), "previous install should be kept"


def test_backups_stay_out_of_the_plugins_directory(
    env_and_state, install_root, backup_dir, artefact
):
    """BaluHost treats every directory under installed/ that carries a
    plugin.json as a plugin, so a backup parked next to the install shows up in
    the Plugins page as a second entry with the same display name — and loads
    stale code if anyone enables it."""
    env, _, _ = env_and_state

    _run(env, install_root, backup_dir, "--artefact", str(artefact))

    strays = [p.name for p in install_root.iterdir() if p.name != "balu_code"]
    assert strays == [], f"nothing but the install belongs here: {strays}"


def test_stale_backups_are_moved_out_of_the_plugins_directory(
    env_and_state, install_root, backup_dir, artefact
):
    """Earlier versions of the script parked backups next to the install."""
    env, _, _ = env_and_state
    stale = install_root / "balu_code.bak-20260101-120000"
    stale.mkdir()
    (stale / "plugin.json").write_text('{"name": "balu_code"}')

    result = _run(env, install_root, backup_dir, "--artefact", str(artefact))

    assert result.returncode == 0, result.stdout + result.stderr
    assert not stale.exists(), "stale backup should have been moved away"
    assert (backup_dir / stale.name / "plugin.json").exists()


def test_a_plugin_that_never_mounts_is_rolled_back(
    env_and_state, install_root, backup_dir, artefact
):
    """403 means the request fell through to BaluHost's sandbox catch-all, i.e.
    the plugin router was never mounted. Restore, restart, fail loudly."""
    env, state, _ = env_and_state
    env["STUB_HTTP_CODE"] = "403"
    env["HEALTH_TIMEOUT"] = "6"

    result = _run(env, install_root, backup_dir, "--artefact", str(artefact))

    assert result.returncode != 0
    assert "rolled back" in result.stderr
    assert (install_root / "balu_code" / "marker.txt").read_text() == "previous\n"
    assert state.read_text().strip() == "running", "a failed deploy must not leave it stopped"


def test_unknown_owner_fails_before_the_service_is_stopped(env_and_state, install_root, backup_dir):
    """The first attempt at this script died on `chown: invalid user` *after*
    stopping the backend, leaving it down. Owner validation is preflight now."""
    env, state, log = env_and_state

    result = _run(env, install_root, backup_dir, "--owner", "nosuchuser:nosuchgroup")

    assert result.returncode != 0
    assert "does not exist" in result.stderr
    assert "systemctl stop" not in log.read_text()
    assert state.read_text().strip() == "running"
    assert (install_root / "balu_code" / "marker.txt").exists()


def test_owner_is_derived_from_the_systemd_unit(env_and_state, install_root, backup_dir, artefact):
    """BaluHost's service template carries User= as a placeholder, so the owner
    differs per install and must not be hardcoded."""
    env, _, _ = env_and_state

    result = _run(env, install_root, backup_dir, "--artefact", str(artefact))

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"owner from baluhost-backend: {getpass.getuser()}:" in result.stdout
