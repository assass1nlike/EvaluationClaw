#!/bin/bash
# Host-side fetcher: downloads the Subway Surfers APK that cannot live in git.
# Run once on the host before launching the env. Idempotent.
#
# SOURCE: APKPure CDN (APKPure displays SHA-256 on the download page, verified
#         2026-05-04 to match the local copy sourced from APKMirror).
#   https://apkpure.com/subway-surfers-2025/com.kiloo.subwaysurf/download/3.57.1
#   Direct: https://d.apkpure.com/b/APK/com.kiloo.subwaysurf?versionCode=88332&nc=arm64-v8a%2Carmeabi-v7a&sv=23
#
# PACKAGE:       com.kiloo.subwaysurf
# VERSION NAME:  3.57.1
# VERSION CODE:  88332 (APKPure internal) / 1055792361676 (Play Store)
# SHA-256:       053c70d370fde4f234a73a8500b490c5c86f21da0061d2d513944d2dc82bb652
# SIZE:          226,501,966 bytes (216.01 MiB)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APK_PATH="$SCRIPT_DIR/apks/subway_surfers.apk"
EXPECTED_SHA256="053c70d370fde4f234a73a8500b490c5c86f21da0061d2d513944d2dc82bb652"

mkdir -p "$(dirname "$APK_PATH")"

if [ -f "$APK_PATH" ] && echo "${EXPECTED_SHA256}  ${APK_PATH}" | sha256sum -c - >/dev/null 2>&1; then
    echo "[ok] subway_surfers.apk already present and verified"
    exit 0
fi

echo "[fetch] subway_surfers.apk (226 MB — may take a minute)"
curl -fsSL --retry 3 --retry-delay 5 --max-time 600 \
    -A "Mozilla/5.0 (Linux; Android 11; Pixel 5)" \
    -H "Referer: https://apkpure.com/subway-surfers-2025/com.kiloo.subwaysurf/download/3.57.1" \
    -o "${APK_PATH}.tmp" \
    "https://d.apkpure.com/b/APK/com.kiloo.subwaysurf?versionCode=88332&nc=arm64-v8a%2Carmeabi-v7a&sv=23"

echo "${EXPECTED_SHA256}  ${APK_PATH}.tmp" | sha256sum -c -
mv "${APK_PATH}.tmp" "$APK_PATH"
echo "[ok] subway_surfers.apk downloaded and verified"
