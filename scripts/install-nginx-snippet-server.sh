#!/usr/bin/env bash
# Idempotent installer for the BaluHost-Ollama proxy nginx location block.
#
# Runs once on the BaluHost server. Locates /etc/nginx/sites-available/baluhost,
# inserts the location block from docs/remote-client/nginx.example.conf right
# before the HTTPS server block's closing brace if missing, then nginx -t +
# reload. Re-running is a no-op once installed.

set -euo pipefail

SITE_CONFIG="${SITE_CONFIG:-/etc/nginx/sites-available/baluhost}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNIPPET_PATH="${SNIPPET_PATH:-${REPO_ROOT}/docs/remote-client/nginx.example.conf}"
MARKER="location /api/plugins/balu_code/ollama/"

if [[ "${EUID}" -ne 0 ]]; then
    echo "This script must run as root (sudo bash $0)" >&2
    exit 1
fi

if [[ ! -f "${SITE_CONFIG}" ]]; then
    echo "nginx config not found: ${SITE_CONFIG}" >&2
    echo "Set SITE_CONFIG=/path/to/your/site if it lives elsewhere." >&2
    exit 1
fi

if [[ ! -f "${SNIPPET_PATH}" ]]; then
    echo "snippet not found: ${SNIPPET_PATH}" >&2
    exit 1
fi

if grep -qF "${MARKER}" "${SITE_CONFIG}"; then
    echo "Location block already present in ${SITE_CONFIG} — nothing to do."
    echo "Running nginx -t anyway as a sanity check..."
    nginx -t
    exit 0
fi

# Use Python to splice the snippet in. Locating the right closing brace
# in nginx config with sed is fragile; Python's a safer pair of hands.
python3 - "${SITE_CONFIG}" "${SNIPPET_PATH}" <<'PY'
import re
import shutil
import sys
from pathlib import Path

site_path = Path(sys.argv[1])
snippet_path = Path(sys.argv[2])

src = site_path.read_text()
snippet = snippet_path.read_text().rstrip() + "\n"

# Find the HTTPS server block: `server { ... listen 443 ssl ...` then walk braces.
m = re.search(r"\nserver \{[^}]*listen\s+443\s+ssl", src)
if not m:
    sys.stderr.write("could not locate HTTPS server block (listen 443 ssl) in config\n")
    sys.exit(2)

start = m.start() + 1  # position of 'server {'
depth = 0
i = start
while i < len(src):
    ch = src[i]
    if ch == "{":
        depth += 1
    elif ch == "}":
        depth -= 1
        if depth == 0:
            break
    i += 1
else:
    sys.stderr.write("unbalanced braces in HTTPS server block\n")
    sys.exit(2)

# Insertion point: just before the closing '}' (which lives at index i).
# Walk back to the last newline so we land on a clean indent boundary.
insert_at = src.rfind("\n", 0, i) + 1

# Indent the snippet to 4 spaces (matches surrounding location blocks).
indented = "".join(
    ("    " + line if line.strip() else line) + ("\n" if not line.endswith("\n") else "")
    for line in snippet.splitlines(keepends=False)
)

new_src = src[:insert_at] + indented + "\n" + src[insert_at:]

# Back up the original before overwriting.
backup = site_path.with_suffix(site_path.suffix + ".bak-balucode")
shutil.copy2(site_path, backup)
site_path.write_text(new_src)
print(f"inserted snippet into {site_path} (backup at {backup})")
PY

echo "Validating nginx config..."
if ! nginx -t; then
    echo
    echo "nginx -t failed. The original config was backed up to ${SITE_CONFIG}.bak-balucode" >&2
    echo "Restore with: sudo cp ${SITE_CONFIG}.bak-balucode ${SITE_CONFIG}" >&2
    exit 1
fi

echo "Reloading nginx..."
systemctl reload nginx
echo "Done. /api/plugins/balu_code/ollama/ now has a dedicated location block."
