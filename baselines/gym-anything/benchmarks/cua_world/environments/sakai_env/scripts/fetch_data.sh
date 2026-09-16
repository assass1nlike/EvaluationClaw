#!/bin/bash
# Host-side fetcher: restores sakai-deploy/ before launching the env.
#
# IMPORTANT — READ BEFORE RUNNING:
#
# sakai-deploy/ is a LOCAL MAVEN REBUILD of Sakai 25.0, not an extraction
# of the official sakai-bin-25.0.tar.gz release tarball. The Sakai-specific
# JARs and WAR files were compiled locally (Built-By: pranjala) and differ
# in sha256 from the official Apereo release build (Built-By: earle).
#
# Because no public mirror hosts the exact local build artifacts, this script
# cannot restore sakai-deploy/ from the internet. Instead it validates an
# existing copy or directs you to the authoritative backup.
#
# Authoritative backup (byte-identical to the original):
#   /compute/babel-l5-20/pranjala/
#     Gym-Anything_for_cmu_super_clean/examples/sakai_env/sakai-deploy/
#
# To restore from backup, run (on a machine with access):
#   rsync -a \
#     /compute/babel-l5-20/pranjala/Gym-Anything_for_cmu_super_clean/examples/sakai_env/sakai-deploy/ \
#     "$(dirname "$0")/../sakai-deploy/"
#
# Official Sakai 25.0 binary tarball (for reference / third-party JARs only):
#   URL:  https://source.sakaiproject.org/release/25.0/artifacts/sakai-bin-25.0.tar.gz
#   MD5:  9edf85706259f2205c384269ba7d9dac
#   Note: 641 third-party JARs in this tarball match the local build byte-for-byte.
#         All 100 WAR files and 317 Sakai 25.0 JARs differ (rebuild artifacts).
#
# See: scratch/data_sources/sakai_env.md for the full sha256 audit.
set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_DIR="$ENV_DIR/sakai-deploy"

# ── Spot-check: verify a representative sample of known-good files ────────────
check_file() {
    local rel="$1" expected_sha="$2"
    local path="$DEPLOY_DIR/$rel"
    if [ ! -f "$path" ]; then
        echo "[MISSING] $rel"
        return 1
    fi
    actual=$(sha256sum "$path" | awk '{print $1}')
    if [ "$actual" != "$expected_sha" ]; then
        echo "[MISMATCH] $rel"
        echo "  expected: $expected_sha"
        echo "  actual:   $actual"
        return 1
    fi
    echo "[ok] $rel"
}

if [ ! -d "$DEPLOY_DIR" ]; then
    echo ""
    echo "ERROR: sakai-deploy/ not found at $DEPLOY_DIR"
    echo ""
    echo "sakai-deploy/ cannot be downloaded from a public source."
    echo "Restore it from the authoritative backup:"
    echo ""
    echo "  rsync -a \\"
    echo "    /compute/babel-l5-20/pranjala/Gym-Anything_for_cmu_super_clean/examples/sakai_env/sakai-deploy/ \\"
    echo "    \"$DEPLOY_DIR/\""
    echo ""
    exit 1
fi

echo "=== sakai-deploy/ found — verifying representative files ==="

# Spot-check: 3 third-party JARs (match tarball byte-for-byte)
check_file \
    "lib/log4j-core-2.24.3.jar" \
    "7eb4084596ae25bd3c61698e48e8d0ab65a9260758884ed5cbb9c6e55c44a56a"

check_file \
    "components/accountvalidator-impl/WEB-INF/lib/generic-dao-0.12.1.jar" \
    "3a0711de32850d9b5eaaeae6471f7adf0749e2cb6cc0f186b51c097682cc43e2"

check_file \
    "lib/jdom2-2.0.6.1.jar" \
    "0b20f45e3a0fd8f0d12cdc5316b06776e902b1365db00118876f9175c60f302c"

# Spot-check: 2 Sakai 25.0 artifacts (local rebuild — do NOT match tarball)
check_file \
    "lib/sakai-kernel-api-25.0.jar" \
    "c5212c36323ba2e9c1c9ab2699ae7fdc38aea3af4e016c48a0e5512ae64eb467"

check_file \
    "webapps/portal.war" \
    "845b87c4f4a46dd9388b564c688c16d58b068ac6ec83e6580bc98d355ef463d3"

FILE_COUNT=$(find "$DEPLOY_DIR" -type f | wc -l)
if [ "$FILE_COUNT" -lt 2050 ]; then
    echo ""
    echo "WARNING: expected 2050 files, found $FILE_COUNT"
    echo "The deploy tree may be incomplete."
    exit 1
fi

echo ""
echo "All spot-checks passed. sakai-deploy/ has $FILE_COUNT files."
echo "Ready to launch the env."
