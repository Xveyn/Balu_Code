#!/usr/bin/env bash
#
# Install this checkout into the BaluHost running on the same machine.
#
# Builds the .bhplugin from the working tree, swaps it into
# <install-root>/<plugin-name>, restarts the backend and then verifies that the
# plugin actually came back. If anything goes wrong after the swap, the previous
# directory is restored and the service started again — a failed deploy never
# leaves the backend stopped.
#
# There is no upload route in BaluHost for local plugins: installing means
# placing the directory under backend/app/plugins/installed/ and restarting.
# That is what this script automates.
#
# Plugin *data* (projects DB, opencode.json, the opencode binary, the runtime
# password) lives in the service user's ~/.local/share/balu-code and is never
# touched here — only the code directory is replaced.
#
# Usage:
#   scripts/deploy-local.sh                          # build, install, restart
#   scripts/deploy-local.sh --artefact x.bhplugin    # install a prebuilt archive
#   scripts/deploy-local.sh --no-restart             # swap files only
#
# The file owner defaults to the User=/Group= of the systemd unit, so it follows
# whatever the install actually uses. Every other default can be overridden by
# flag or environment variable:
#   INSTALL_ROOT, SERVICE, OWNER, BACKEND_URL, KEEP_BACKUPS, HEALTH_TIMEOUT
#
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/baluhost/backend/app/plugins/installed}"
SERVICE="${SERVICE:-baluhost-backend}"
OWNER="${OWNER:-}"          # empty = derive from the systemd unit
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
KEEP_BACKUPS="${KEEP_BACKUPS:-3}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-60}"
ARTEFACT=""
RESTART=1

say() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() {
    # the header comment block, up to the first line of actual code
    awk 'NR > 2 && /^#/ { sub(/^# ?/, ""); print; next } NR > 2 { exit }' "$0"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --artefact) ARTEFACT="${2:?--artefact needs a path}"; shift 2 ;;
        --install-root) INSTALL_ROOT="${2:?--install-root needs a path}"; shift 2 ;;
        --service) SERVICE="${2:?--service needs a unit name}"; shift 2 ;;
        --owner) OWNER="${2:?--owner needs user:group}"; shift 2 ;;
        --backend-url) BACKEND_URL="${2:?--backend-url needs a URL}"; shift 2 ;;
        --no-restart) RESTART=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument: $1 (try --help)" ;;
    esac
done

# --------------------------------------------------------------------------
# Preflight — everything that can be checked before the service is touched is
# checked here. A deploy that is going to fail should fail while the old plugin
# is still serving.
# --------------------------------------------------------------------------

[ -f plugin/plugin.json ] || die "run this from the repository root (no plugin/plugin.json here)"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v curl >/dev/null 2>&1 || die "curl is required"
[ -d "$INSTALL_ROOT" ] || die "install root does not exist: $INSTALL_ROOT"

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    command -v sudo >/dev/null 2>&1 || die "not running as root and sudo is not available"
    SUDO="sudo"
fi

systemctl cat "$SERVICE" >/dev/null 2>&1 || die "systemd unit not found: ${SERVICE} (pass --service)"

# Ownership follows the unit rather than a guess: BaluHost's own service
# template carries User= as a placeholder, so installs differ from box to box.
if [ -z "$OWNER" ]; then
    owner_user=$(systemctl show "$SERVICE" -p User --value 2>/dev/null || true)
    owner_group=$(systemctl show "$SERVICE" -p Group --value 2>/dev/null || true)
    [ -n "$owner_user" ] || owner_user="root"   # no User= in the unit means root
    [ -n "$owner_group" ] || owner_group="$owner_user"
    OWNER="${owner_user}:${owner_group}"
    say "owner from ${SERVICE}: ${OWNER}"
else
    owner_user="${OWNER%%:*}"
    owner_group="${OWNER#*:}"
fi

id -u "$owner_user" >/dev/null 2>&1 || die "user '${owner_user}' does not exist — pass --owner user:group"
if command -v getent >/dev/null 2>&1; then
    getent group "$owner_group" >/dev/null 2>&1 || die "group '${owner_group}' does not exist — pass --owner user:group"
fi

NAME=$(python3 -c 'import json; print(json.load(open("plugin/plugin.json"))["name"])')
VERSION=$(python3 -c 'import json; print(json.load(open("plugin/plugin.json"))["version"])')
TARGET="${INSTALL_ROOT}/${NAME}"

if [ -z "$ARTEFACT" ]; then
    say "building ${NAME} ${VERSION}"
    python3 -m scripts.build_bhplugin --repo-root . --dist dist/
    ARTEFACT="dist/${NAME}-${VERSION}.bhplugin"
fi
[ -f "$ARTEFACT" ] || die "artefact not found: $ARTEFACT"

if [ -f "${ARTEFACT}.sha256" ]; then
    expected=$(awk '{print $1}' "${ARTEFACT}.sha256")
    actual=$(python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$ARTEFACT")
    [ "$expected" = "$actual" ] || die "checksum mismatch for ${ARTEFACT}"
    say "checksum ok"
fi

# Unpack into a staging dir first: a truncated or malformed archive then fails
# before the installed plugin has been touched.
STAGE=$(mktemp -d)
BACKUP=""
SERVICE_STOPPED=0
SWAPPED=0

cleanup() {
    if [ -n "${STAGE:-}" ] && [ -d "$STAGE" ]; then
        rm -rf "$STAGE"
    fi
    return 0
}
trap cleanup EXIT

say "unpacking ${ARTEFACT}"
python3 -m zipfile -e "$ARTEFACT" "$STAGE"
[ -f "$STAGE/plugin.json" ] || die "archive has no plugin.json at its root: ${ARTEFACT}"

# --------------------------------------------------------------------------
# Failure handling — from here on the service may be stopped and the target
# directory may be half-replaced, so every exit path has to put both back.
# --------------------------------------------------------------------------

restore_previous() {
    if [ "$SWAPPED" -eq 1 ] && [ -n "$BACKUP" ] && [ -d "$BACKUP" ]; then
        say "restoring $(basename "$BACKUP")"
        $SUDO rm -rf "$TARGET"
        $SUDO cp -a "$BACKUP" "$TARGET"
    fi
}

ensure_service_running() {
    if [ "$RESTART" -eq 0 ]; then
        return 0
    fi
    say "starting ${SERVICE}"
    if $SUDO systemctl start "$SERVICE"; then
        SERVICE_STOPPED=0
    else
        say "could not start ${SERVICE} — check: journalctl -u ${SERVICE} -n 50"
    fi
}

on_failure() {
    trap - ERR
    say "deploy failed — undoing"
    restore_previous
    if [ "$SERVICE_STOPPED" -eq 1 ]; then
        ensure_service_running
    elif [ "$SWAPPED" -eq 1 ] && [ "$RESTART" -eq 1 ]; then
        say "restarting ${SERVICE} with the previous version"
        $SUDO systemctl restart "$SERVICE" || say "could not restart ${SERVICE}"
    fi
    die "rolled back — check: journalctl -u ${SERVICE} -n 50"
}
trap on_failure ERR

if [ "$RESTART" -eq 1 ]; then
    say "stopping ${SERVICE}"
    $SUDO systemctl stop "$SERVICE"
    SERVICE_STOPPED=1
fi

if [ -d "$TARGET" ]; then
    BACKUP="${TARGET}.bak-$(date +%Y%m%d-%H%M%S)"
    say "keeping current install as $(basename "$BACKUP")"
    $SUDO cp -a "$TARGET" "$BACKUP"
fi

say "installing into ${TARGET}"
$SUDO rm -rf "$TARGET"
$SUDO mv "$STAGE" "$TARGET"
STAGE=""  # moved into place; nothing left to clean up
SWAPPED=1
$SUDO chown -R "$OWNER" "$TARGET"

if [ "$RESTART" -eq 1 ]; then
    ensure_service_running

    # 200 = the plugin's own router answered, so the plugin loaded.
    # 401/403 = the request fell through to the sandbox catch-all, which means
    # the plugin router was never mounted — a load failure, not a slow start.
    # No answer = backend still coming up; keep waiting.
    say "waiting for /api/plugins/${NAME}/health"
    deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
    code=""
    while [ "$(date +%s)" -lt "$deadline" ]; do
        code=$(curl -s -o /dev/null -w '%{http_code}' "${BACKEND_URL}/api/plugins/${NAME}/health" || true)
        case "$code" in
            200) break ;;
            401|403)
                say "backend is up but the plugin router is not mounted (HTTP ${code})"
                false  # hand over to the ERR trap
                ;;
        esac
        sleep 2
    done
    if [ "$code" != "200" ]; then
        say "health check did not pass within ${HEALTH_TIMEOUT}s (last response: ${code:-none})"
        false  # hand over to the ERR trap
    fi
    say "healthy: $(curl -s "${BACKEND_URL}/api/plugins/${NAME}/health")"
fi

trap - ERR

if [ "$KEEP_BACKUPS" -gt 0 ]; then
    ls -1dt "${TARGET}.bak-"* 2>/dev/null | tail -n "+$((KEEP_BACKUPS + 1))" | while read -r old; do
        say "pruning $(basename "$old")"
        $SUDO rm -rf "$old"
    done
fi

say "done — ${NAME} ${VERSION} installed"

if [ "$RESTART" -eq 1 ]; then
    cat <<EOF

Next: point the plugin at a model, e.g.

  curl -si -X PUT ${BACKEND_URL}/api/plugins/${NAME}/config \\
    -H "Authorization: Bearer \$TOKEN" -H 'Content-Type: application/json' \\
    -d '{"chat_model":"qwen3.8-code:latest","context_window":32768,"think":false}'

The X-Balu-Code-Runtime-Restarted response header says whether the embedded
opencode runtime picked the change up. "false" means the request hit a worker
that does not own the runtime — restart ${SERVICE} in that case.
EOF
fi
