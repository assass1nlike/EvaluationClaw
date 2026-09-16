#!/bin/bash
# Host-side fetcher: downloads large/external assets that cannot live in git.
# Run once on the host before launching the env.
#
# Oracle Analytics Desktop installer (Oracle_Analytics_Desktop_January2026_Win.exe)
# REQUIRES a manual download: Oracle SSO login is mandatory via eDelivery.
# See NEEDS_HUMAN_REVIEW note below.
#
# This script is idempotent.
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

# ---------------------------------------------------------------------------
# sample_order_lines2023.xlsx
# Oracle's published OAC sample data (publicly available, no login required).
# Source: Oracle Analytics Cloud tutorial page
# ---------------------------------------------------------------------------
fetch \
    "https://docs.oracle.com/en/cloud/paas/analytics-cloud/tutorial-export-to-excel/files/sample_order_lines2023.xlsx" \
    "$ENV_DIR/data/sample_order_lines2023.xlsx" \
    "551ed7b30900540fbac8461945fc246172cd7ca313cbad68d48b2ff7197d2dd3"

# ---------------------------------------------------------------------------
# NEEDS_HUMAN_REVIEW: Oracle_Analytics_Desktop_January2026_Win.exe
#
# Oracle distributes Analytics Desktop exclusively through Oracle eDelivery /
# Oracle Software Delivery Cloud, which requires a free Oracle SSO login.
# No public direct-download URL exists; eDelivery generates authenticated
# session-scoped URLs that cannot be scripted without credentials.
#
# To obtain the installer:
#   1. Sign in at https://edelivery.oracle.com/
#   2. Search for "Oracle Analytics Desktop"
#   3. Select the January 2026 update, platform "Microsoft Windows x64"
#   4. Accept the license and download the ZIP
#   5. Extract Oracle_Analytics_Desktop_January2026_Win.exe from the ZIP
#   6. Verify sha256:
#      39c23201e25a1ff6ece2cccf5ef4f1d1c8a31711f120eca198e50294f81c82f7
#   7. Place the file at:
#      benchmarks/cua_world/environments/oracle_analytics_desktop_env/data/Oracle_Analytics_Desktop_January2026_Win.exe
# ---------------------------------------------------------------------------
EXE="$ENV_DIR/data/Oracle_Analytics_Desktop_January2026_Win.exe"
EXPECTED_SHA="39c23201e25a1ff6ece2cccf5ef4f1d1c8a31711f120eca198e50294f81c82f7"
if [ -f "$EXE" ] && echo "${EXPECTED_SHA}  ${EXE}" | sha256sum -c - >/dev/null 2>&1; then
    echo "[ok] Oracle_Analytics_Desktop_January2026_Win.exe already present and verified"
else
    echo "[NEEDS_HUMAN_REVIEW] Oracle_Analytics_Desktop_January2026_Win.exe must be downloaded manually."
    echo "  Visit https://edelivery.oracle.com/ (free Oracle SSO required)."
    echo "  Expected sha256: ${EXPECTED_SHA}"
    echo "  Place at: ${EXE}"
    exit 1
fi

echo "All assets verified."
