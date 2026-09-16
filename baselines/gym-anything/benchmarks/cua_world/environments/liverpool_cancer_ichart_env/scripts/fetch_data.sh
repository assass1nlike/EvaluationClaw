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
        -A "Mozilla/5.0 (Linux; Android 11; Pixel 5)" \
        -H "Referer: https://apkpure.com/cancer-ichart/com.liverpooluni.ichartoncology/download/1.0.1" \
        -o "$out.tmp" "$url"
    echo "${sha}  ${out}.tmp" | sha256sum -c -
    mv "$out.tmp" "$out"
}

# Cancer iChart 1.0.1 (com.liverpooluni.ichartoncology, versionCode=8)
# Source: APKPure CDN — https://d.apkpure.com/b/APK/com.liverpooluni.ichartoncology?versionCode=8
# redirects to https://d-15.winudf.com/b/APK/Y29tLmxpdmVycG9vbHVuaS5pY2hhcnRvbmNvbG9neV84XzEyZDllMDc0
# SHA-256 verified 2026-05-04 against local copy.
fetch \
    "https://d.apkpure.com/b/APK/com.liverpooluni.ichartoncology?versionCode=8" \
    "$ENV_DIR/scripts/apks/com.liverpooluni.ichartoncology.apk" \
    "265521ca63c39a1770930c8e6efcae6bfc8e5764c0364b5faf648a5326aae076"

echo "All assets verified."
