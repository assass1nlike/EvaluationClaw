#!/bin/bash
# Host-side fetcher: downloads the ICIJ Offshore Leaks full CSV bundle and
# extracts the first 100 Panama Papers intermediary rows used by this env.
# Run once on the host before launching the env. Idempotent.
set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${ENV_DIR}/data"
OUT="${DATA_DIR}/panama_papers_intermediaries.csv"
SHA="014715ffc20e6d41ee51dbc94a8c0ca7bb67a5ad59b99f99a7edcf7cfda5278c"

ZIP_URL="https://offshoreleaks-data.icij.org/offshoreleaks/csv/full-oldb.LATEST.zip"
ZIP_ENTRY="nodes-intermediaries.csv"

if [ -f "${OUT}" ] && echo "${SHA}  ${OUT}" | sha256sum -c - >/dev/null 2>&1; then
    echo "[ok] panama_papers_intermediaries.csv already present and verified"
    exit 0
fi

echo "[fetch] Downloading ICIJ Offshore Leaks bundle (~70 MB)..."
TMP_ZIP="$(mktemp /tmp/full-oldb.XXXXXX.zip)"
curl -fsSL --retry 3 --retry-delay 5 --max-time 600 -o "${TMP_ZIP}" "${ZIP_URL}"

echo "[extract] Extracting first 100 rows of ${ZIP_ENTRY}..."
mkdir -p "${DATA_DIR}"
TMP_OUT="${OUT}.tmp"
# head closes the pipe after 101 lines; SIGPIPE (141) from unzip is expected and benign.
{ unzip -p "${TMP_ZIP}" "${ZIP_ENTRY}" | head -101 > "${TMP_OUT}"; } || true
rm -f "${TMP_ZIP}"
# Abort if the extract produced nothing meaningful (real error, not SIGPIPE)
[ -s "${TMP_OUT}" ] || { echo "[error] Extract produced empty output"; exit 1; }

echo "[verify] Checking sha256..."
echo "${SHA}  ${TMP_OUT}" | sha256sum -c -
mv "${TMP_OUT}" "${OUT}"

echo "[ok] panama_papers_intermediaries.csv written and verified"
