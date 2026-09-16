#!/bin/bash
# Host-side fetcher: downloads the PhysioNet EEG Motor Movement/Imagery Dataset
# source EDF files that the container converts into OpenBCI-format playback data.
#
# These EDF files are NOT the bundled .txt files in data/; they are the upstream
# canonical source used by the conversion script in install_openbci.sh.
# Run this script if you need to reproduce or audit the EDF-to-OpenBCI conversion
# outside of a container build.
#
# Dataset: PhysioNet eegmmidb 1.0.0
# License: Open Data Commons Attribution License v1.0
# Citation: Schalk G, McFarland DJ, Hinterberger T, Birbaumer N, Wolpaw JR (2004)
#           BCI2000: a general-purpose brain-computer interface (BCI) system.
#           IEEE Trans Biomed Eng 51(6):1034-1043
#
# This script is idempotent: re-running it is safe.
set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EDF_DIR="${ENV_DIR}/data/edf_source"

fetch() {
    local url="$1" out="$2" sha="$3"
    if [ -f "$out" ] && echo "${sha}  ${out}" | sha256sum -c - >/dev/null 2>&1; then
        echo "[ok] $(basename "$out") already present and verified"
        return 0
    fi
    echo "[fetch] $(basename "$out")"
    mkdir -p "$(dirname "$out")"
    curl -fsSL --retry 3 --retry-delay 5 --max-time 600 -o "${out}.tmp" "$url"
    echo "${sha}  ${out}.tmp" | sha256sum -c -
    mv "${out}.tmp" "$out"
}

# S001R01.edf — Subject 001, Run 01 (eyes open baseline)
# Used to generate: OpenBCI-EEG-S001-EyesOpen.txt and OpenBCI_GUI-v5-EEGEyesOpen.txt
fetch \
    "https://physionet.org/files/eegmmidb/1.0.0/S001/S001R01.edf" \
    "${EDF_DIR}/S001R01.edf" \
    "4743b736131a7e147c150e8b37711029b6cda5e356c4b3e8261a03cdcaaf8b0c"

# S001R04.edf — Subject 001, Run 04 (motor imagery: left/right fist)
# Used to generate: OpenBCI-EEG-S001-MotorImagery.txt
fetch \
    "https://physionet.org/files/eegmmidb/1.0.0/S001/S001R04.edf" \
    "${EDF_DIR}/S001R04.edf" \
    "3d161f88e1c00632585287d2ce584c2bc0f08862438eb255ea8723e00fac693d"

echo "All EDF source files verified."
echo "Location: ${EDF_DIR}/"
echo ""
echo "NOTE: The .txt playback files in data/ were generated from these EDFs"
echo "using the Python converter in install_openbci.sh. The .txt files are"
echo "non-reproducible byte-for-byte across NumPy/scipy versions (signed-zero"
echo "float formatting differs). The bundled .txt files in data/ are the"
echo "canonical versions for this repo."
