#!/bin/bash
# Host-side fetcher: downloads .vital case files from the VitalDB Open Dataset.
# Source: PhysioNet mirror of VitalDB v1.0.0 (https://physionet.org/content/vitaldb/1.0.0/)
# Run once on the host before launching the env. Idempotent.
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

BASE_URL="https://physionet.org/files/vitaldb/1.0.0/vital_files"

fetch \
    "${BASE_URL}/0001.vital" \
    "$ENV_DIR/data/0001.vital" \
    "742a1ab3342e21daa99135b74f7511f815e72f9a2b4eec8900babb156aa84a45"

fetch \
    "${BASE_URL}/0002.vital" \
    "$ENV_DIR/data/0002.vital" \
    "a5d95f675c2a8af52c03a97d6e6389f2eba23a8b6c43332cf6e79149fc9f47ec"

fetch \
    "${BASE_URL}/0003.vital" \
    "$ENV_DIR/data/0003.vital" \
    "573db0941d580167833f84497f5d1c4a1391443eeec3f95852287ea09db024e4"

echo "All assets verified."
