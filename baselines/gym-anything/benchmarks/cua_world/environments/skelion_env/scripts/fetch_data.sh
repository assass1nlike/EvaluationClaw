#!/bin/bash
# Host-side fetcher: downloads large/external assets that cannot live in git.
# Run once on the host before launching the env.
#
# Windows env hooks run inside the Windows guest with a read-only mount of
# scripts/ and data/, so the installer must be present on the host before the
# env starts. install_sketchup_skelion.ps1 copies it from C:\workspace\data\.
# This script is idempotent.
#
# NOTE: Skelion.rbz (v5.5.2) has no public canonical source and is NOT
# fetched here. It must be supplied manually — see scratch/data_sources/skelion_env.md.
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
    "https://archive.org/download/sketchupmake2017/sketchupmake-2017-2-2555-90782-en-x64.exe" \
    "$ENV_DIR/data/SketchUpMake2017.exe" \
    "9841792f170d803ae95a2741c44cce38e618660f98a1a3816335e9bf1b45a337"

echo "All assets verified."
