#!/bin/bash
# Host-side fetcher: downloads large/external assets that cannot live in git.
# Run once on the host before launching the env.
#
# Windows env hooks run inside the Windows guest with a read-only mount of
# scripts/ and data/, so the MSI must be present on the host before the env
# starts. install_multiecuscan.ps1 copies it from C:\workspace\data\ first.
# This script is idempotent.
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
    "https://www.multiecuscan.net/SetupMultiecuscan54.msi" \
    "$ENV_DIR/data/SetupMultiecuscan.msi" \
    "3a9e575bf54efc07ebfeb42ad6b89d6e3f79f1bdfb1fd3f54e7e751f1e0019c4"

echo "All assets verified."
