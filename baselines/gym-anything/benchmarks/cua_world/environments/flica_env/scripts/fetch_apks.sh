#!/usr/bin/env bash
# fetch_apks.sh — download Flight Crew View 3.9.4 split APKs (versionCode 1511)
# from the APKPure CDN XAPK and verify byte identity for 3 of 4 splits.
#
# Usage:
#   bash fetch_apks.sh [--dest <dir>]
#
# The fourth split (config.xxhdpi.apk) has no public byte-identical source;
# APKPure's XAPK ships config.xhdpi instead.  That file must be sourced
# manually from Google Play (e.g. via a device backup + adb pull).
#
# Expected SHA-256 (verified Feb 2026 against Play Store originals):
#   com.robert.fcView.apk   72d6ecf692b6953306d952840851014c7db2f930bf352358a4326e7f2f04e23b
#   config.arm64_v8a.apk    8263c5561a5e1776661f56815454734f26ed32d45f6e959c873985e0317e8bba
#   config.en.apk           01d3c79d3c56e200f02a43d7106d19e5cb54cf3231db66e6a7fd8049a56af2a6
#   config.xxhdpi.apk       0473f477703825924eac26e2442aaedc1375e8957f27e50af0ac16772c97cba1  (manual only)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${DEST:-$SCRIPT_DIR/apks}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dest) DEST="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

mkdir -p "$DEST"

# APKPure CDN — XAPK for com.robert.fcView versionCode 1511 (3.9.4)
# URL confirmed live 2026-05-04; redirect resolved from apkpure.net.
XAPK_URL="https://d-12.winudf.com/b/XAPK/Y29tLnJvYmVydC5mY1ZpZXdfMTUxMV9hY2E3NTlmOQ?_fn=RmxpZ2h0IENyZXcgVmlld18zLjkuNF9BUEtQdXJlLnhhcGs&_p=Y29tLnJvYmVydC5mY1ZpZXc%3D&is_hot=false&k=672c04b3d5aa10d677cdac7a16ac3dc469f97311"
XAPK_SHA256="998c0e4bde768202f3c3368e1854ad246945563add89a871278937619de47572"

XAPK_TMP="$(mktemp /tmp/flica_394_XXXXXX.xapk)"
trap 'rm -f "$XAPK_TMP"' EXIT

echo "[fetch_apks] Downloading Flight Crew View 3.9.4 XAPK (~45 MB)..."
curl -fsSL \
    -H "User-Agent: Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36" \
    --connect-timeout 30 --max-time 300 \
    -o "$XAPK_TMP" \
    "$XAPK_URL"

echo "[fetch_apks] Verifying XAPK integrity..."
ACTUAL_SHA="$(sha256sum "$XAPK_TMP" | cut -d' ' -f1)"
if [[ "$ACTUAL_SHA" != "$XAPK_SHA256" ]]; then
    echo "ERROR: XAPK sha256 mismatch." >&2
    echo "  expected: $XAPK_SHA256" >&2
    echo "  got:      $ACTUAL_SHA" >&2
    echo "The CDN URL may have rotated. See docs/scratch/data_sources/flica_env.md" >&2
    exit 1
fi

echo "[fetch_apks] Extracting split APKs..."
EXTRACT_TMP="$(mktemp -d /tmp/flica_extract_XXXXXX)"
trap 'rm -f "$XAPK_TMP"; rm -rf "$EXTRACT_TMP"' EXIT

unzip -q "$XAPK_TMP" \
    "com.robert.fcView.apk" \
    "config.arm64_v8a.apk" \
    "config.en.apk" \
    -d "$EXTRACT_TMP"

echo "[fetch_apks] Verifying individual split sha256..."
declare -A EXPECTED=(
    ["com.robert.fcView.apk"]="72d6ecf692b6953306d952840851014c7db2f930bf352358a4326e7f2f04e23b"
    ["config.arm64_v8a.apk"]="8263c5561a5e1776661f56815454734f26ed32d45f6e959c873985e0317e8bba"
    ["config.en.apk"]="01d3c79d3c56e200f02a43d7106d19e5cb54cf3231db66e6a7fd8049a56af2a6"
)

ALL_OK=1
for FNAME in "${!EXPECTED[@]}"; do
    GOT="$(sha256sum "$EXTRACT_TMP/$FNAME" | cut -d' ' -f1)"
    if [[ "$GOT" == "${EXPECTED[$FNAME]}" ]]; then
        echo "  OK  $FNAME"
    else
        echo "  FAIL $FNAME" >&2
        echo "       expected: ${EXPECTED[$FNAME]}" >&2
        echo "       got:      $GOT" >&2
        ALL_OK=0
    fi
done

if [[ "$ALL_OK" -ne 1 ]]; then
    echo "ERROR: One or more splits failed sha256 verification." >&2
    exit 1
fi

echo "[fetch_apks] Installing splits to $DEST ..."
for FNAME in "${!EXPECTED[@]}"; do
    cp "$EXTRACT_TMP/$FNAME" "$DEST/$FNAME"
done

echo ""
echo "[fetch_apks] Done. 3 of 4 splits installed:"
ls -lh "$DEST"/com.robert.fcView.apk "$DEST"/config.arm64_v8a.apk "$DEST"/config.en.apk
echo ""
echo "MANUAL STEP REQUIRED:"
echo "  config.xxhdpi.apk has no public byte-identical source."
echo "  APKPure ships config.xhdpi (different density tier)."
echo "  Source it from a Play Store device backup:"
echo "    adb shell pm path com.robert.fcView"
echo "    adb pull <path-to-split_config.xxhdpi.apk> $DEST/config.xxhdpi.apk"
echo "  Expected sha256: 0473f477703825924eac26e2442aaedc1375e8957f27e50af0ac16772c97cba1"
