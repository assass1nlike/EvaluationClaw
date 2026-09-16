#!/bin/bash
# Host-side fetcher: downloads large/external assets that cannot live in git.
# Run once on the host before launching the env.
#
# AVD hooks run inside the emulator with a read-only mount of scripts/, so the
# APK has to be present on the host before reset(). This script is idempotent.
set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")/.." && pwd)"

fetch() {
    local url="$1" out="$2" sha="$3" ua="$4"
    if [ -f "$out" ] && echo "${sha}  ${out}" | sha256sum -c - >/dev/null 2>&1; then
        echo "[ok] $(basename "$out") already present and verified"
        return 0
    fi
    echo "[fetch] $(basename "$out")"
    mkdir -p "$(dirname "$out")"
    curl -fsSL --retry 3 --retry-delay 5 --max-time 600 \
        -A "$ua" \
        -o "$out.tmp" "$url"
    echo "${sha}  ${out}.tmp" | sha256sum -c -
    mv "$out.tmp" "$out"
}

# farmOS Field Kit v0.8.0 (org.farmos.app, GPL-3.0)
# Sourced from download.pureapk.com (mirrors Google Play).
# The Dalvik user-agent is required; the signed query params are stable content tokens.
fetch \
    "https://download.pureapk.com/b/APK/b3JnLmZhcm1vcy5hcHBfODAwXzhkZmYxZWMy?as2=b6ef580a6799666569025a0668735eba6bd2be2d&k=52af93a9a8bd1c033722f0a57c619afb6bd2be2d&_p=b3JnLmZhcm1vcy5hcHA&c=1%7CBUSINESS%7Cb2lkPTkmZGV2PWZhcm1PUyZ0PWFwayZzPTEwNDIxOTcwJnZuPTAuOC4wJnZjPTgwMA&_fn=ZmFybU9TK0ZpZWxkK0tpdF8wLjguMF9hcGtjb21iby5jb20uYXBr" \
    "$ENV_DIR/scripts/apks/org.farmos.app.apk" \
    "546647f208c6492f5f18c54b9508465db0ad97951a90019aa30385e863044def" \
    "Dalvik/2.1.0 (Linux; U; Android 11; Pixel 4 Build/RQ3A.210805.001)"

echo "All assets verified."
