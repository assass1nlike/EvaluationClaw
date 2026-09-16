#!/bin/bash
# Host-side fetcher: downloads large/external assets that cannot live in git.
# Run once on the host before launching the env.
#
# AVD hooks run inside the emulator with a read-only mount of scripts/, so the
# APK has to be present on the host before reset(). This script is idempotent.
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
    curl -fsSL --retry 3 --retry-delay 5 --max-time 600 \
        -H "User-Agent: Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36" \
        -o "$out.tmp" "$url"
    echo "${sha}  ${out}.tmp" | sha256sum -c -
    mv "$out.tmp" "$out"
}

# HSN Electrical Calculations v2.2.8 (versionCode 66)
# Source: APKPure — byte-verified against original (sha256 confirmed identical)
fetch \
    "https://d.apkpure.com/b/APK/com.hsn.electricalcalculations?versionCode=66" \
    "$ENV_DIR/scripts/apks/com.hsn.electricalcalculations.apk" \
    "34d848a77e6833119469d416e1bdafc7597b50cfba02bc276b1a1c15d08d15e8"

echo "All assets verified."
