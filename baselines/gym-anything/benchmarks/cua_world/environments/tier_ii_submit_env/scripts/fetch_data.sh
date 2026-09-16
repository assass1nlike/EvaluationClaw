#!/bin/bash
# Host-side fetcher: downloads large/external assets that cannot live in git.
# Run once on the host before launching the env.
#
# The installer is read-only-mounted into the Windows VM at
# C:\workspace\data\tier2submit_installer.exe and consumed by
# scripts/install_tier2submit.ps1 during the pre_start hook.
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
    "https://www.epa.gov/system/files/other-files/2026-02/tier2submit2025installer_rev1.exe" \
    "$ENV_DIR/data/tier2submit_installer.exe" \
    "21824a24ab388974cc368e7e5ad22f43db3d98cf17e2f9ac63ca7c134b6ecf46"

echo "All assets verified."
