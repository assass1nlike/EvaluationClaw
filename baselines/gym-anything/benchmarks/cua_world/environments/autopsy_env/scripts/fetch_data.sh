#!/bin/bash
# Host-side fetcher: downloads large/external assets that cannot live in git.
# Run once on the host before launching the env. Idempotent.
#
# Downloads the DFTT #8 "JPEG Search" practice disk image by Brian Carrier
# (Digital Forensics Tool Testing, https://dftt.sourceforge.net/test8/index.html).
# Public-domain DFIR education material.
set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TASK_DIR="$ENV_DIR/tasks/file_slack_space_extraction"

ZIP_URL="https://prdownloads.sourceforge.net/dftt/8-jpeg-search.zip?download"
ZIP_OUT="$TASK_DIR/8-jpeg-search.zip"
ZIP_SHA="fdc681ae976291e47fdd3db3b7958493cbcc8879e867a0fc372e7190de153bdb"
EXTRACT_DIR="$TASK_DIR/8-jpeg-search"

# ── helpers ──────────────────────────────────────────────────────────────────
ok()   { echo "[ok]    $*"; }
info() { echo "[fetch] $*"; }
die()  { echo "[error] $*" >&2; exit 1; }

verify_zip() {
    echo "${ZIP_SHA}  ${ZIP_OUT}" | sha256sum -c - >/dev/null 2>&1
}

# ── skip if already present and verified ─────────────────────────────────────
if [ -f "$ZIP_OUT" ] && verify_zip; then
    ok "8-jpeg-search.zip already present and verified"
else
    info "8-jpeg-search.zip (DFTT #8 -- Brian Carrier / sleuthkit.org)"
    mkdir -p "$TASK_DIR"
    curl -fsSL --retry 3 --retry-delay 5 --max-time 300 \
        -o "${ZIP_OUT}.tmp" "$ZIP_URL"
    echo "${ZIP_SHA}  ${ZIP_OUT}.tmp" | sha256sum -c - \
        || die "sha256 mismatch on downloaded zip -- aborting"
    mv "${ZIP_OUT}.tmp" "$ZIP_OUT"
    ok "8-jpeg-search.zip downloaded and verified"
fi

# ── extract if directory is missing or empty ─────────────────────────────────
if [ ! -f "$EXTRACT_DIR/8-jpeg-search.dd" ]; then
    info "Extracting 8-jpeg-search.zip -> $EXTRACT_DIR/"
    rm -rf "$EXTRACT_DIR"
    unzip -q "$ZIP_OUT" -d "$TASK_DIR"
    ok "Extracted"
else
    ok "8-jpeg-search/ already extracted"
fi

echo "All assets verified."
