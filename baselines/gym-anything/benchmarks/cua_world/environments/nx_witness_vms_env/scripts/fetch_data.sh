#!/usr/bin/env bash
# Host-side fetcher: downloads video anomaly detection datasets for the nx_witness_vms_env.
# Run once on the host before launching the env. Idempotent: re-running skips verified files.
#
# Downloads (all freely available, no auth):
#   Mall Dataset (CUHK)    88 MB   https://personal.ie.cuhk.edu.hk/~ccloy/
#   Avenue Dataset (CUHK) 776 MB   http://www.cse.cuhk.edu.hk/leojia/
#   UMN Crowd Dataset      24 MB   https://mha.cs.umn.edu/
#   UCSD Anomaly Dataset  706 MB   http://www.svcl.ucsd.edu/projects/anomaly/
#
# After downloading, runs scripts/prepare_video_data.py to generate the five
# task videos and the JSON ground-truth annotations from the raw archives.
#
# See scratch/data_sources/nx_witness_vms_env.md for full provenance notes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DATA_DIR="${ENV_DIR}/data"
CACHE_DIR="${DATA_DIR}/.cache"

mkdir -p "${CACHE_DIR}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

fetch() {
    local url="$1" out="$2" sha="$3" desc="${4:-}"
    if [ -f "${out}" ] && echo "${sha}  ${out}" | sha256sum -c - >/dev/null 2>&1; then
        echo "[ok] ${desc:-$(basename "${out}")} already present and verified"
        return 0
    fi
    echo "[fetch] ${desc:-$(basename "${out}")}"
    mkdir -p "$(dirname "${out}")"
    wget -q --no-check-certificate --timeout=1200 -O "${out}.tmp" "${url}"
    echo "${sha}  ${out}.tmp" | sha256sum -c -
    mv "${out}.tmp" "${out}"
    echo "[ok] $(basename "${out}") downloaded and verified"
}

extract_zip_file() {
    # Extract a single member from a zip, writing to a destination path.
    # If dest already exists and sha matches, skip.
    local zip="$1" member="$2" dest="$3" sha="$4"
    if [ -f "${dest}" ] && echo "${sha}  ${dest}" | sha256sum -c - >/dev/null 2>&1; then
        return 0
    fi
    mkdir -p "$(dirname "${dest}")"
    python3 -c "
import zipfile, sys
zip_path, member, dest = sys.argv[1], sys.argv[2], sys.argv[3]
with zipfile.ZipFile(zip_path) as zf:
    with zf.open(member) as src, open(dest, 'wb') as dst:
        dst.write(src.read())
" "${zip}" "${member}" "${dest}"
    echo "${sha}  ${dest}" | sha256sum -c -
}

# ---------------------------------------------------------------------------
# 1. Mall Dataset (CUHK)
#    sha256: 21baea1066ea1473289c28c2f9fc8440cea3c8d8905b83a66529fbef184d47e3
#    The zip contains mall_dataset/ with 2000 JPEG frames + 3 .mat annotation files.
#    We verify the zip itself, then extract the whole archive plus copy annotations.
# ---------------------------------------------------------------------------

echo ""
echo "=== Mall Dataset (CUHK) ==="
MALL_ZIP="${DATA_DIR}/mall_dataset.zip"
fetch \
    "https://personal.ie.cuhk.edu.hk/~ccloy/files/datasets/mall_dataset.zip" \
    "${MALL_ZIP}" \
    "21baea1066ea1473289c28c2f9fc8440cea3c8d8905b83a66529fbef184d47e3" \
    "Mall Dataset (88 MB)"

# Extract the full archive (creates data/mall_dataset/)
MALL_EXTRACT="${DATA_DIR}/mall_dataset"
if [ ! -d "${MALL_EXTRACT}/mall_dataset/frames" ]; then
    echo "[extract] mall_dataset.zip -> data/mall_dataset/"
    python3 -c "
import zipfile, os, sys
zip_path, dest = sys.argv[1], sys.argv[2]
os.makedirs(dest, exist_ok=True)
with zipfile.ZipFile(zip_path) as zf:
    zf.extractall(dest)
" "${MALL_ZIP}" "${MALL_EXTRACT}"
    echo "[ok] mall_dataset/ extracted"
fi

# Extract annotation .mat files into data/annotations/
echo "[annotations] mall_gt.mat, mall_feat.mat, perspective_roi.mat"
extract_zip_file \
    "${MALL_ZIP}" "mall_dataset/mall_gt.mat" \
    "${DATA_DIR}/annotations/mall_gt.mat" \
    "aa2fb21370c9c12d279a4bf1835ea51da91adf4c65e86f76a91ca23a2e51583a"

extract_zip_file \
    "${MALL_ZIP}" "mall_dataset/mall_feat.mat" \
    "${DATA_DIR}/annotations/mall_feat.mat" \
    "efbe173c875ff2849301adfea43a4898b3ceebf63d6980fca9c042e1348d0394"

extract_zip_file \
    "${MALL_ZIP}" "mall_dataset/perspective_roi.mat" \
    "${DATA_DIR}/annotations/perspective_roi.mat" \
    "aa8ca5fe26b755bbac55562ca33c338597bffddf7ac7c367e2269749ea20de7f"

echo "[ok] mall annotations verified"

# ---------------------------------------------------------------------------
# 2. Avenue Dataset (CUHK)
#    sha256: fc9cb8432a11ca79c18aa180c72524011411b69d3b0ff27c8816e41c0de61531
#    Canonical source: http://www.cse.cuhk.edu.hk/leojia/projects/detectabnormal/
#    Contains 37 .avi training/testing videos + 37 .mat annotation files.
#    Raw archive is cached; prepare_video_data.py consumes it to generate avenue_*.mp4.
# ---------------------------------------------------------------------------

echo ""
echo "=== Avenue Dataset (CUHK) ==="
AVENUE_ZIP="${CACHE_DIR}/avenue_dataset.zip"
fetch \
    "http://www.cse.cuhk.edu.hk/leojia/projects/detectabnormal/Avenue_Dataset.zip" \
    "${AVENUE_ZIP}" \
    "fc9cb8432a11ca79c18aa180c72524011411b69d3b0ff27c8816e41c0de61531" \
    "Avenue Dataset (776 MB)"

# ---------------------------------------------------------------------------
# 3. UMN Crowd Dataset
#    sha256: 9ca315dc099a98ada2fb5b34138f354768ff3fed440f7c18bf81c7759668def7
#    Canonical source: https://mha.cs.umn.edu/Movies/Crowd-Activity-All.avi
#    Single combined AVI (3 scenes). prepare_video_data.py extracts scene 2 (indoor).
# ---------------------------------------------------------------------------

echo ""
echo "=== UMN Crowd Dataset ==="
UMN_AVI="${CACHE_DIR}/umn_crowd.avi"
fetch \
    "https://mha.cs.umn.edu/Movies/Crowd-Activity-All.avi" \
    "${UMN_AVI}" \
    "9ca315dc099a98ada2fb5b34138f354768ff3fed440f7c18bf81c7759668def7" \
    "UMN Crowd Dataset (24 MB)"

# ---------------------------------------------------------------------------
# 4. UCSD Anomaly Dataset
#    sha256: 2329af326951f5097fdd114c50e853957d3e569493a49d22fc082a9fd791915b
#    Canonical source: http://www.svcl.ucsd.edu/projects/anomaly/UCSD_Anomaly_Dataset.tar.gz
#    Contains UCSDped1 + UCSDped2 frame sequences (.tif). prepare_video_data.py
#    builds ucsd_pedestrian.mp4 from Ped2 Train001-005 + Test008.
# ---------------------------------------------------------------------------

echo ""
echo "=== UCSD Anomaly Dataset ==="
UCSD_TAR="${CACHE_DIR}/ucsd_anomaly.tar.gz"
fetch \
    "http://www.svcl.ucsd.edu/projects/anomaly/UCSD_Anomaly_Dataset.tar.gz" \
    "${UCSD_TAR}" \
    "2329af326951f5097fdd114c50e853957d3e569493a49d22fc082a9fd791915b" \
    "UCSD Anomaly Dataset (706 MB)"

# ---------------------------------------------------------------------------
# Generate task videos and JSON annotations
#    prepare_video_data.py reads the cached archives and writes:
#      data/videos/mall_pedestrian.mp4
#      data/videos/avenue_anomaly.mp4 + avenue_normal.mp4
#      data/videos/umn_crowd.mp4
#      data/videos/ucsd_pedestrian.mp4
#      data/annotations/*_gt.json  (5 files)
# ---------------------------------------------------------------------------

echo ""
echo "=== Generating task videos and annotations ==="
VIDEOS_OK=1
for vid in mall_pedestrian.mp4 avenue_anomaly.mp4 avenue_normal.mp4 umn_crowd.mp4 ucsd_pedestrian.mp4; do
    if [ ! -f "${DATA_DIR}/videos/${vid}" ]; then
        VIDEOS_OK=0
        break
    fi
done

if [ "${VIDEOS_OK}" -eq 1 ]; then
    echo "[ok] All task videos already present — skipping prepare_video_data.py"
else
    echo "[run] scripts/prepare_video_data.py"
    python3 "${SCRIPT_DIR}/prepare_video_data.py"
fi

echo ""
echo "All datasets fetched and verified."
echo "Videos:"
ls -lh "${DATA_DIR}/videos/"
echo "Annotations:"
ls -lh "${DATA_DIR}/annotations/"
