#!/bin/bash
# Host-side fetcher: downloads large/external assets that cannot live in git.
# Run once on the host before launching the env.
#
# The installer is mounted read-only into the Windows VM via env.json mounts,
# so it must be present on the host before reset(). This script is idempotent.
set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")/.." && pwd)"

fetch() {
    local url="$1" out="$2" sha="$3"
    if [ -f "$out" ] && echo "${sha}  ${out}" | sha256sum -c - >/dev/null 2>&1; then
        echo "[ok] $(basename "$out") already present and verified"
        return 0
    fi
    echo "[fetch] $(basename "$out")"
    mkdir -p "$(dirname "$out")"
    curl -fsSL --retry 3 --retry-delay 5 --max-time 600 -o "$out.tmp" "$url"
    echo "${sha}  ${out}.tmp" | sha256sum -c -
    mv "$out.tmp" "$out"
}

fetch \
    "https://www.epa.gov/system/files/other-files/2025-12/cameodatamanager451installer.exe" \
    "$ENV_DIR/data/cameodatamanager451installer.exe" \
    "7453dd6a52d66e6ae0f42f6827b994b7290160ef129511e7cc8841d16b59b91f"

echo "All assets verified."
