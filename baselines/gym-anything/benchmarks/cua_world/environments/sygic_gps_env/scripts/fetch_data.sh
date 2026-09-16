#!/bin/bash
# Host-side fetcher: downloads large/external assets that cannot live in git.
# Run once on the host before launching the env. Idempotent.
#
# SOURCE: APKPure CDN (APKPure displays SHA-256 on the download page, verified
#         2026-05-04 to match the local copy).
#   https://apkpure.com/sygic-gps-navigation-maps-for-mobile/com.sygic.aura/download/26.0.2-105446
#   Direct: https://d.apkpure.com/b/APK/com.sygic.aura?versionCode=261260002
#
# PACKAGE:       com.sygic.aura
# VERSION NAME:  26.0.2-105446
# VERSION CODE:  261260002
# SHA-256:       84d538b376375ba3bd755799e9fd32445c545bde7335f45ea16852ef4a44a623
# SIZE:          161,150,061 bytes (153.7 MiB)
# ARCH:          arm64-v8a, Android 8.0+
set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APK="$ENV_DIR/scripts/apks/com.sygic.aura.apk"
SHA="84d538b376375ba3bd755799e9fd32445c545bde7335f45ea16852ef4a44a623"

if [ -f "$APK" ] && echo "${SHA}  ${APK}" | sha256sum -c - >/dev/null 2>&1; then
    echo "[ok] com.sygic.aura.apk already present and verified"
    echo "All assets verified."
    exit 0
fi

echo "[fetch] com.sygic.aura.apk (154 MB — may take a minute)"
mkdir -p "$(dirname "$APK")"
curl -fsSL --retry 3 --retry-delay 5 --max-time 600 \
    -A "Mozilla/5.0 (Linux; Android 11; Pixel 5)" \
    -H "Referer: https://apkpure.com/sygic-gps-navigation-maps-for-mobile/com.sygic.aura/download/26.0.2-105446" \
    -o "${APK}.tmp" \
    "https://d.apkpure.com/b/APK/com.sygic.aura?versionCode=261260002"

echo "${SHA}  ${APK}.tmp" | sha256sum -c -
mv "${APK}.tmp" "$APK"
echo "[ok] com.sygic.aura.apk downloaded and verified"
echo "All assets verified."
