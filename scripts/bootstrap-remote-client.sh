#!/usr/bin/env bash
# Bootstrap a client laptop to run opencode locally against a BaluHost remote Ollama.
#
# What it does (idempotent):
#   1. Downloads the pinned opencode binary if missing, verifies sha256.
#   2. Writes ~/.config/opencode/opencode.json from the in-repo template.
#   3. Prompts once for the BaluHost API key, saves it to
#      ~/.config/balu-code/api_key (mode 0600).
#   4. Prints the export line the user needs in their shell rc.
#
# Re-running on an already-bootstrapped host:
#   - re-verifies the binary,
#   - re-renders the config (picks up new server URL / model),
#   - keeps the saved API key unless the user passes --new-key.

set -euo pipefail

OPENCODE_VERSION="1.14.50"
OPENCODE_TRIPLE="linux-x64"
OPENCODE_SHA256="2c4abf29d5765f535f10ffec748aa38939d5441750abbdb5001a4307d33349ae"
OPENCODE_URL="https://github.com/sst/opencode/releases/download/v${OPENCODE_VERSION}/opencode-${OPENCODE_TRIPLE}.tar.gz"

INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/balu-code-client}"
BINARY_PATH="${INSTALL_DIR}/opencode"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
CONFIG_FILE="${CONFIG_DIR}/opencode.json"
KEY_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/balu-code"
KEY_FILE="${KEY_DIR}/api_key"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_PATH="${REPO_ROOT}/docs/remote-client/opencode.json.tmpl"

NEW_KEY=0
for arg in "$@"; do
    case "$arg" in
        --new-key) NEW_KEY=1 ;;
        -h|--help)
            echo "Usage: $(basename "$0") [--new-key]"
            echo "Env: BASE_URL, MODEL, NUM_CTX (defaults shown when prompted)"
            exit 0
            ;;
    esac
done

prompt() {
    local prompt_text="$1" default="$2" reply
    read -rp "${prompt_text} [${default}]: " reply
    echo "${reply:-$default}"
}

# --- 1. Binary ---
mkdir -p "${INSTALL_DIR}"
need_download=1
if [[ -f "${BINARY_PATH}" ]]; then
    actual="$(sha256sum "${BINARY_PATH}" | awk '{print $1}')"
    if [[ "${actual}" == "${OPENCODE_SHA256}" ]]; then
        echo "opencode binary already present and verified."
        need_download=0
    else
        echo "opencode binary checksum mismatch; will re-download."
    fi
fi
if [[ "${need_download}" -eq 1 ]]; then
    echo "Downloading opencode ${OPENCODE_VERSION} (${OPENCODE_TRIPLE})..."
    tmpdir="$(mktemp -d)"
    trap 'rm -rf "${tmpdir}"' EXIT
    curl -fsSL "${OPENCODE_URL}" -o "${tmpdir}/opencode.tar.gz"
    tar -xzf "${tmpdir}/opencode.tar.gz" -C "${tmpdir}"
    extracted="$(find "${tmpdir}" -type f -name opencode -perm -u+x | head -n1)"
    if [[ -z "${extracted}" ]]; then
        echo "could not find opencode binary inside tarball" >&2
        exit 1
    fi
    actual="$(sha256sum "${extracted}" | awk '{print $1}')"
    if [[ "${actual}" != "${OPENCODE_SHA256}" ]]; then
        echo "checksum mismatch: expected ${OPENCODE_SHA256}, got ${actual}" >&2
        exit 1
    fi
    mv "${extracted}" "${BINARY_PATH}"
    chmod 0755 "${BINARY_PATH}"
    echo "opencode installed to ${BINARY_PATH}"
fi

# --- 2. API key ---
mkdir -p "${KEY_DIR}"
chmod 0700 "${KEY_DIR}"
if [[ -f "${KEY_FILE}" && "${NEW_KEY}" -eq 0 ]]; then
    echo "Reusing existing API key in ${KEY_FILE}."
else
    echo
    echo "Create a BaluHost API key:"
    echo "  https://YOUR-BALUHOST/users  →  Profile  →  API Keys  →  New"
    echo "It must start with 'balu_'."
    read -rsp "Paste API key: " api_key
    echo
    if [[ -z "${api_key}" || "${api_key}" != balu_* ]]; then
        echo "Refusing to save: key is empty or has no 'balu_' prefix." >&2
        exit 1
    fi
    umask 077
    printf '%s' "${api_key}" > "${KEY_FILE}"
    chmod 0600 "${KEY_FILE}"
    echo "API key saved to ${KEY_FILE}."
fi

# --- 3. Config ---
mkdir -p "${CONFIG_DIR}"
api_key_value="$(cat "${KEY_FILE}")"
base_url="${BASE_URL:-$(prompt "BaluHost base URL (without trailing slash)" "https://baluhost.example")}"
model="${MODEL:-$(prompt "Default model" "qwen2.5-coder:14b")}"
num_ctx="${NUM_CTX:-$(prompt "Context window (num_ctx)" "32768")}"

full_base="${base_url%/}/api/plugins/balu_code/ollama/api"

# Use python rather than sed to keep escaping sane (api keys contain '/' and '+').
python3 - "${TEMPLATE_PATH}" "${CONFIG_FILE}" \
    "${full_base}" "${api_key_value}" "${model}" "${num_ctx}" <<'PY'
import sys, pathlib
tmpl_path, out_path, base_url, api_key, model, num_ctx = sys.argv[1:]
tmpl = pathlib.Path(tmpl_path).read_text()
out = (tmpl
       .replace("__BASE_URL__", base_url)
       .replace("__API_KEY__", api_key)
       .replace("__MODEL__", model)
       .replace("__NUM_CTX__", str(int(num_ctx))))
pathlib.Path(out_path).write_text(out)
PY
chmod 0600 "${CONFIG_FILE}"
echo "opencode config written to ${CONFIG_FILE}"

# --- 4. PATH hint ---
echo
echo "Done. Add this to your shell rc if ${INSTALL_DIR} isn't on PATH yet:"
echo "  export PATH=\"${INSTALL_DIR}:\$PATH\""
echo
echo "Then: cd into a project and run:  opencode"
