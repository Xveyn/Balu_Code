#!/usr/bin/env bash
#
# Install this checkout into the BaluHost running on the same machine.
#
# Builds the .bhplugin from the working tree, swaps it into
# <install-root>/<plugin-name>, restarts the backend and then verifies that the
# plugin actually came back. If it did not, the previous directory is restored
# and the backend restarted again — a failed deploy leaves a running plugin
# rather than a broken one.
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
# Every default can be overridden by flag or environment variable:
#   INSTALL_ROOT, SERVICE, OWNER, BACKEND_URL, KEEP_BACKUPS, HEALTH_TIMEOUT
#
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/baluhost/backend/app/plugins/installed}"
SERVICE="${SERVICE:-baluhost-backend}"
OWNER="${OWNER:-baluhost:baluhost}"
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

[ -f plugin/plugin.json ] || die "run this from the repository root (no plugin/plugin.json here)"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
[ -d "$INSTALL_ROOT" ] || die "install root does not exist: $INSTALL_ROOT"

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    command -v sudo >/dev/null 2>&1 || die "not running as root and sudo is not available"
    SUDO="sudo"
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

rollback() {
    if [ -z "$BACKUP" ]; then
        die "deploy failed and there was no previous install to restore — check: journalctl -u ${SERVICE} -n 50"
    fi
    say "rolling back to $(basename "$BACKUP")"
    $SUDO rm -rf "$TARGET"
    $SUDO cp -a "$BACKUP" "$TARGET"
    if [ "$RESTART" -eq 1 ]; then
        $SUDO systemctl restart "$SERVICE"
    fi
    die "deploy failed and was rolled back — check: journalctl -u ${SERVICE} -n 50"
}

if [ "$RESTART" -eq 1 ]; then
    say "stopping ${SERVICE}"
    $SUDO systemctl stop "$SERVICE"
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
$SUDO chown -R "$OWNER" "$TARGET"

if [ "$RESTART" -eq 1 ]; then
    say "starting ${SERVICE}"
    $SUDO systemctl start "$SERVICE"

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
                rollback
                ;;
        esac
        sleep 2
    done
    if [ "$code" != "200" ]; then
        say "health check did not pass within ${HEALTH_TIMEOUT}s (last response: ${code:-none})"
        rollback
    fi
    say "healthy: $(curl -s "${BACKEND_URL}/api/plugins/${NAME}/health")"
fi

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
