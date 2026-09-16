#!/bin/bash
# OpenELIS Global Installation Script (pre_start hook)
# Installs Docker, docker-compose-plugin (v2), Firefox, and UI automation tools.
# Pre-pulls all OpenELIS Docker images to speed up post_start.

set -euo pipefail

echo "=== Installing OpenELIS Global prerequisites ==="

export DEBIAN_FRONTEND=noninteractive

echo "Updating package lists..."
apt-get update

# Install Docker — use docker.io + docker-compose (v1 fallback) plus try v2 plugin.
# IMPORTANT: use docker-compose-plugin (v2) NOT docker-compose (v1) per cross-cutting patterns.
echo "Installing Docker + Compose..."
apt-get install -y docker.io
# Try docker-compose-plugin first (provides 'docker compose' v2)
apt-get install -y docker-compose-plugin 2>/dev/null \
    || apt-get install -y docker-compose-v2 2>/dev/null \
    || apt-get install -y docker-compose 2>/dev/null \
    || echo "WARNING: docker-compose install fell through; will rely on docker.io built-in"

systemctl enable docker
systemctl start docker

# Allow ga user to run docker without sudo
usermod -aG docker ga || true

echo "Installing Firefox + automation tools..."
apt-get install -y \
    firefox \
    wmctrl \
    xdotool \
    x11-utils \
    xclip \
    scrot \
    imagemagick \
    curl \
    jq \
    ca-certificates \
    netcat-openbsd \
    libnss3-tools \
    dbus-x11 \
    libcanberra-gtk-module \
    libcanberra-gtk3-module \
    python3 \
    python3-requests

# Wait for Docker daemon to be fully ready
echo "Waiting for Docker daemon..."
for i in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then
        echo "Docker daemon is ready"
        break
    fi
    sleep 2
done

# Authenticate with Docker Hub to avoid rate limits
echo "${DOCKERHUB_TOKEN:-}" | docker login -u "${DOCKERHUB_USERNAME:-}" --password-stdin 2>/dev/null || true

# Pre-pull all OpenELIS Docker images
echo "Pre-pulling OpenELIS Docker images (this may take several minutes)..."
docker pull itechuw/certgen:main || true
docker pull itechuw/openelis-global-2-database:develop || true
docker pull itechuw/openelis-global-2:develop || true
docker pull itechuw/openelis-global-2-fhir:develop || true
docker pull itechuw/openelis-global-2-frontend:develop || true
docker pull itechuw/openelis-global-2-proxy:develop || true
docker pull willfarrell/autoheal:1.2.0 || true

# ─── Fetch MIMIC-III Clinical Database Demo v1.4 CSVs ───
# Source: https://physionet.org/content/mimiciii-demo/1.4/
# Public, no credentials required (ODC-BY licence).
# These two files are not bundled in the repo; they are downloaded at build time
# and verified by sha256 before being placed in /workspace/data/.
echo "Fetching MIMIC-III Demo CSVs..."

MIMIC_BASE="https://physionet.org/files/mimiciii-demo/1.4"
DATA_DIR="/workspace/data"

# Expected sha256 checksums (byte-identical to PhysioNet originals)
LABEVENTS_SHA256="bca32a7242e739c0cbf1690270db83c10e38a27dbfa915eeb14f5a31a1e898fa"
LABITEMS_SHA256="c573653bd06915e48a5fb5f3db01d75554350ec1a628aa91d01ef36daa4eae7f"

fetch_and_verify() {
    local url="$1"
    local dest="$2"
    local expected_sha256="$3"
    local label="$4"

    echo "  Downloading ${label}..."
    if ! curl -fsSL --connect-timeout 60 --max-time 300 "${url}" -o "${dest}"; then
        echo "  ERROR: Failed to download ${label}" >&2
        return 1
    fi

    local actual_sha256
    actual_sha256=$(sha256sum "${dest}" | awk '{print $1}')
    if [ "${actual_sha256}" != "${expected_sha256}" ]; then
        echo "  ERROR: sha256 mismatch for ${label}" >&2
        echo "    expected: ${expected_sha256}" >&2
        echo "    actual:   ${actual_sha256}" >&2
        rm -f "${dest}"
        return 1
    fi

    echo "  OK: ${label} sha256 verified"
    return 0
}

mkdir -p "${DATA_DIR}"

if [ ! -f "${DATA_DIR}/mimic_labevents.csv" ]; then
    fetch_and_verify \
        "${MIMIC_BASE}/LABEVENTS.csv" \
        "${DATA_DIR}/mimic_labevents.csv" \
        "${LABEVENTS_SHA256}" \
        "MIMIC-III LABEVENTS.csv"
else
    echo "  mimic_labevents.csv already present, skipping download"
fi

if [ ! -f "${DATA_DIR}/mimic_labitems.csv" ]; then
    fetch_and_verify \
        "${MIMIC_BASE}/D_LABITEMS.csv" \
        "${DATA_DIR}/mimic_labitems.csv" \
        "${LABITEMS_SHA256}" \
        "MIMIC-III D_LABITEMS.csv"
else
    echo "  mimic_labitems.csv already present, skipping download"
fi

echo "MIMIC-III Demo CSVs ready in ${DATA_DIR}"

apt-get clean
rm -rf /var/lib/apt/lists/*

echo ""
echo "=== OpenELIS Installation Complete ==="
echo "Docker: $(docker --version 2>/dev/null || echo 'not found')"
# Detect which compose command is available
if docker compose version >/dev/null 2>&1; then
    echo "Docker Compose: $(docker compose version 2>/dev/null)"
elif command -v docker-compose >/dev/null 2>&1; then
    echo "Docker Compose (v1): $(docker-compose --version 2>/dev/null)"
fi
echo "Firefox: $(firefox --version 2>/dev/null || echo 'not found')"
echo "Images pulled:"
docker images --format "  {{.Repository}}:{{.Tag}} ({{.Size}})" 2>/dev/null | grep -E "itechuw|autoheal" || true
