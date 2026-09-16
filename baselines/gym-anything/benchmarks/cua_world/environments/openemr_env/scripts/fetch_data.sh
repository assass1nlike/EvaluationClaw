#!/bin/bash
# Host-side fetcher: downloads large/external assets that cannot live in git.
# Run once on the host before launching the env.
#
# Downloads the Synthea 10k COVID-19 CSV sample bundle, verifies its sha256,
# and extracts it to synthea/ in the env directory. Idempotent.
set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")/.." && pwd)"

SYNTHEA_URL="https://synthetichealth.github.io/synthea-sample-data/downloads/10k_synthea_covid19_csv.zip"
SYNTHEA_SHA="559757dc849f4361a328f456d2c0a20c6df72419068321c753c6be787161e937"
SYNTHEA_ZIP="$ENV_DIR/synthea.zip"
SYNTHEA_DIR="$ENV_DIR/synthea"

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

fetch "$SYNTHEA_URL" "$SYNTHEA_ZIP" "$SYNTHEA_SHA"

if [ ! -d "$SYNTHEA_DIR/10k_synthea_covid19_csv" ]; then
    echo "[extract] synthea.zip -> synthea/"
    mkdir -p "$SYNTHEA_DIR"
    unzip -q "$SYNTHEA_ZIP" -d "$SYNTHEA_DIR"
else
    echo "[ok] synthea/ already extracted"
fi

echo "All assets verified."
