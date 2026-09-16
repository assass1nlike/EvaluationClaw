#!/bin/bash
# Host-side fetcher: downloads large/external assets that cannot live in git.
# Run once on the host before launching the env.
#
# This script is idempotent: re-running it skips files that are already
# present and sha256-verified.
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

# NCEP/NCAR Reanalysis air-temperature monthly long-term-mean climatology
# Source: NOAA Physical Sciences Laboratory (PSL)
# https://psl.noaa.gov/data/gridded/data.ncep.reanalysis.derived.surface.html
fetch \
    "https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis.derived/surface/air.mon.ltm.nc" \
    "$ENV_DIR/air.mon.ltm.nc" \
    "31e6f601fd8e1ecc0bd63e9907ae9e0f931fe675c397ab608abe191b15576619"

echo "All assets verified."
