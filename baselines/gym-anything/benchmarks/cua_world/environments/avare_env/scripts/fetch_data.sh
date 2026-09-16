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
    curl -fsSL --retry 3 --retry-delay 5 --max-time 600 -o "$out.tmp" "$url"
    echo "${sha}  ${out}.tmp" | sha256sum -c -
    mv "$out.tmp" "$out"
}

fetch \
    "https://f-droid.org/repo/com.ds.avare_404.apk" \
    "$ENV_DIR/scripts/apks/com.ds.avare.apk" \
    "5ef8f51e1c584d643ebb076b0fa708c4577afaa1ba0049d5f6e699df8cbfb204"

echo "All assets verified."
