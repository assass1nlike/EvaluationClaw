#!/usr/bin/env bash
# fetch_data.sh — host-side pre-run script for jasp_env
#
# Downloads data files that are gitignored from their canonical upstream
# sources and verifies byte-identity via sha256 before placing them.
#
# Run once on the host before `gym-anything run jasp_env ...`:
#   bash benchmarks/cua_world/environments/jasp_env/scripts/fetch_data.sh
#
# Idempotent: existing file with correct sha256 is kept without re-downloading.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../../.." && pwd)"
ENV_DIR="$REPO_ROOT/benchmarks/cua_world/environments/jasp_env"

# ---------------------------------------------------------------------------
# File: tasks/bayesian_ttest/Invisibility_Cloak.csv
#   Source: JASP desktop repository — official sample data library
#   Paper:  Field, A. (2013). Discovering Statistics Using IBM SPSS Statistics
# ---------------------------------------------------------------------------
DEST="$ENV_DIR/tasks/bayesian_ttest/Invisibility_Cloak.csv"
URL="https://raw.githubusercontent.com/jasp-stats/jasp-desktop/master/Resources/Data%20Sets/Data%20Library/2.%20T-Tests/Invisibility%20Cloak.csv"
EXPECTED_SHA256="1be5e89f1fc8a81b8975b24c4af34e4c8051773878990cd061ef94bcf107e262"

fetch_and_verify() {
    local dest="$1" url="$2" expected="$3"
    local name
    name="$(basename "$dest")"

    if [ -f "$dest" ]; then
        actual="$(sha256sum "$dest" | awk '{print $1}')"
        if [ "$actual" = "$expected" ]; then
            echo "OK (cached): $name"
            return 0
        fi
        echo "WARN: $name exists but sha256 mismatch — re-downloading"
        rm -f "$dest"
    fi

    echo "Downloading: $name"
    mkdir -p "$(dirname "$dest")"
    curl -fsSL "$url" -o "$dest"

    actual="$(sha256sum "$dest" | awk '{print $1}')"
    if [ "$actual" != "$expected" ]; then
        echo "ERROR: sha256 mismatch for $name"
        echo "  expected: $expected"
        echo "  got:      $actual"
        rm -f "$dest"
        exit 1
    fi
    echo "VERIFIED: $name  sha256=$actual"
}

fetch_and_verify "$DEST" "$URL" "$EXPECTED_SHA256"

echo "jasp_env data fetch complete."
