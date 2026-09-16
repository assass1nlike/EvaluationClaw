#!/bin/bash
# Host-side fetcher: downloads large/external assets that cannot live in git.
# Run once on the host before launching the env.
#
# Downloads the ReqView DEMO example project (.reqw bundle) from the official
# ReqView desktop distribution and extracts the bundled PNG attachments.
# This script is idempotent.
set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ATTACHMENTS_DIR="$ENV_DIR/data/ExampleProject/attachments"
REQW_URL="https://desktop.reqview.com/data/reqview_demo.reqw"
REQW_TMP="/tmp/reqview_demo_fetch.reqw"
REQW_SHA="18e02c762c64a90323c02f30a4eec378f6daf3c2be717c2bab66ad14f0605c36"

# Expected sha256 for each extracted PNG (derived from the canonical reqw bundle)
declare -A PNG_SHAS=(
    ["ARCH-7_1_reqview_architecture.png"]="445699cadb9c20898d69ef60d7c42a28c7d854e3c4822a38f27994b4abb86ef5"
    ["ASVS-23_1_asvs_40_levels.png"]="e5e51ddbdf058ac5ed905901f07fa6cb760ddb98d06f8448f3d8fdd055e75df4"
    ["ASVS-9_1_license.png"]="6833a94d412073aa8fb8e3e7a945b65506354a11ca4f9200c8f3b65b198b2a83"
    ["INF-2_1_reqview_icon.png"]="61d0457ef59b61f38481eaa6ae7c6825607f8e92cef840382716a193e4a80873"
    ["INF-9_1_Project Traceability Diagram.png"]="f2ac32860357a47945ef86b166987e99b4319e15b679fcc36af2136863c0ea64"
)

all_present() {
    for name in "${!PNG_SHAS[@]}"; do
        local out="$ATTACHMENTS_DIR/$name"
        local sha="${PNG_SHAS[$name]}"
        if ! [ -f "$out" ] || ! echo "${sha}  ${out}" | sha256sum -c - >/dev/null 2>&1; then
            return 1
        fi
    done
    return 0
}

if all_present; then
    echo "[ok] All ReqView PNG attachments already present and verified"
    echo "All assets verified."
    exit 0
fi

echo "[fetch] reqview_demo.reqw"
curl -fsSL --retry 3 --retry-delay 5 --max-time 600 -o "$REQW_TMP" "$REQW_URL"
echo "${REQW_SHA}  ${REQW_TMP}" | sha256sum -c -

echo "[extract] PNG attachments from reqview_demo.reqw"
mkdir -p "$ATTACHMENTS_DIR"

python3 - "$REQW_TMP" "$ATTACHMENTS_DIR" << 'PYEOF'
import json, base64, sys, os

reqw_path, out_dir = sys.argv[1], sys.argv[2]
with open(reqw_path) as f:
    data = json.load(f)

attachments = data.get("attachments", {})
for name, val in attachments.items():
    if not name.endswith(".png"):
        continue
    data_uri = val["data"]
    b64 = data_uri.split(",", 1)[1]
    raw = base64.b64decode(b64)
    out_path = os.path.join(out_dir, name)
    with open(out_path, "wb") as fout:
        fout.write(raw)
    print(f"  extracted: {name} ({len(raw)} bytes)")
PYEOF

rm -f "$REQW_TMP"

echo "[verify] Checking sha256 of extracted PNGs"
FAIL=0
declare -A PNG_SHAS=(
    ["ARCH-7_1_reqview_architecture.png"]="445699cadb9c20898d69ef60d7c42a28c7d854e3c4822a38f27994b4abb86ef5"
    ["ASVS-23_1_asvs_40_levels.png"]="e5e51ddbdf058ac5ed905901f07fa6cb760ddb98d06f8448f3d8fdd055e75df4"
    ["ASVS-9_1_license.png"]="6833a94d412073aa8fb8e3e7a945b65506354a11ca4f9200c8f3b65b198b2a83"
    ["INF-2_1_reqview_icon.png"]="61d0457ef59b61f38481eaa6ae7c6825607f8e92cef840382716a193e4a80873"
    ["INF-9_1_Project Traceability Diagram.png"]="f2ac32860357a47945ef86b166987e99b4319e15b679fcc36af2136863c0ea64"
)
for name in "${!PNG_SHAS[@]}"; do
    out="$ATTACHMENTS_DIR/$name"
    sha="${PNG_SHAS[$name]}"
    if echo "${sha}  ${out}" | sha256sum -c - >/dev/null 2>&1; then
        echo "  [ok] $name"
    else
        echo "  [FAIL] $name — sha256 mismatch"
        FAIL=1
    fi
done

if [ "$FAIL" -ne 0 ]; then
    echo "ERROR: One or more PNG attachments failed sha256 verification"
    exit 1
fi

echo "All assets verified."
