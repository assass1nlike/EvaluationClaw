#!/bin/bash
# Host-side fetcher: downloads Docker image tarballs that cannot live in git.
# Run once on the host before launching the env.
#
# Each image is fetched by its pinned image-ID (sha256 of the config JSON),
# verified with docker inspect after load, and saved to data/docker_images/.
#
# Classification: DIGEST-PINNED
#   Docker image .tar files produced by `docker save` embed the image config
#   digest (sha256 of the config JSON) in the tar's manifest.json and in the
#   repositories file.  The *outer* tar wrapper byte-layout can vary across
#   Docker Engine versions, so byte-level sha256 of the .tar itself is not
#   guaranteed to match across machines.  We therefore pin the IMAGE-ID
#   (sha256 of the config JSON) and verify that after `docker pull && docker save`.
#
# Live verification skipped: docker daemon was not available on the host where
# this fetcher was authored.  Run `docker info` to confirm daemon availability
# before using.
#
# This script is idempotent: if the .tar already exists AND passes image-ID
# verification, it is skipped.

set -euo pipefail

ENV_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMG_DIR="${ENV_DIR}/data/docker_images"
mkdir -p "${IMG_DIR}"

# Fetch a docker image by tag:
#   $1 = docker image reference  (e.g. docker.io/library/alpine:3.18)
#   $2 = output filename          (e.g. alpine_3.18.tar)
#   $3 = expected image-ID sha256 (sha256 of config JSON inside the tar)
fetch_image() {
    local ref="$1"
    local outfile="${IMG_DIR}/$2"
    local expected_id="$3"

    # Check if already present and verified
    if [ -f "${outfile}" ]; then
        actual_id=$(tar -xOf "${outfile}" manifest.json 2>/dev/null \
            | python3 -c "import sys,json; m=json.load(sys.stdin); print(m[0]['Config'].replace('.json',''))" 2>/dev/null || echo "")
        if [ "${actual_id}" = "${expected_id}" ]; then
            echo "[ok] $(basename "${outfile}") already present and verified (image-id: ${expected_id:0:12}...)"
            return 0
        else
            echo "[stale] $(basename "${outfile}") image-id mismatch — re-fetching"
            rm -f "${outfile}"
        fi
    fi

    echo "[fetch] ${ref} → $(basename "${outfile}")"
    docker pull "${ref}"

    # Verify image-ID matches expectation
    actual_id=$(docker inspect --format '{{index .Id}}' "${ref}" 2>/dev/null \
        | sed 's/sha256://')
    if [ "${actual_id}" != "${expected_id}" ]; then
        echo "[warn] image-id after pull is ${actual_id}, expected ${expected_id}" >&2
        echo "       The image may have been updated on Docker Hub.  Re-check digest." >&2
        # We still save it; the caller can decide whether to fail.
    fi

    docker save "${ref}" -o "${outfile}.tmp"

    # Final image-id check on the saved tar
    saved_id=$(tar -xOf "${outfile}.tmp" manifest.json 2>/dev/null \
        | python3 -c "import sys,json; m=json.load(sys.stdin); print(m[0]['Config'].replace('.json',''))" 2>/dev/null || echo "")
    if [ "${saved_id}" != "${expected_id}" ]; then
        echo "[error] saved tar image-id ${saved_id} != expected ${expected_id}" >&2
        rm -f "${outfile}.tmp"
        return 1
    fi

    mv "${outfile}.tmp" "${outfile}"
    echo "[done] $(basename "${outfile}") (image-id: ${expected_id:0:12}...)"
}

# ---------------------------------------------------------------------------
# Images — pinned by image-ID (sha256 of config JSON)
# Tag usage follows setup_docker.sh load order (tasks 1-5).
# ---------------------------------------------------------------------------

# Task 1: vulnerability remediation
fetch_image "docker.io/library/python:3.9-slim-bullseye" \
    "python_3.9-slim-bullseye.tar" \
    "ed6f8d42e44570055a5b6c16df05ff3ad5d129ce4a3bfc8baefad15949952a3f"

fetch_image "docker.io/library/node:18-bullseye-slim" \
    "node_18-bullseye-slim.tar" \
    "1f6e0489132be094e459e5fa2f7053d56fd415197f20bb2786e0726f2d39eca7"

fetch_image "docker.io/library/ubuntu:20.04" \
    "ubuntu_20.04.tar" \
    "b7bab04fd9aa0c771e5720bf0cc7cbf993fd6946645983d9096126e5af45d713"

# Task 2: compose application stack
fetch_image "docker.io/library/postgres:14" \
    "postgres_14.tar" \
    "0056c0f4c9cafbfeac767fe419f4cfc1e61c02fa732b0fb66a366d6735581147"

fetch_image "docker.io/library/redis:7-alpine" \
    "redis_7-alpine.tar" \
    "aa189b5a1954929c393585e6dc5717a75b18f75a931df8bdcc00a3d3bd546be6"

fetch_image "docker.io/library/nginx:1.24-alpine" \
    "nginx_1.24-alpine.tar" \
    "249f59e1dec7f7eacbeba4bb9215b8000e4bdbb672af523b3dacc89915b026ae"

fetch_image "docker.io/library/python:3.11-slim" \
    "python_3.11-slim.tar" \
    "992921a8b23a7d2fd769908f7646e7cccd583fea96486a99ace92c7399768847"

fetch_image "docker.io/library/node:20-slim" \
    "node_20-slim.tar" \
    "b810c2b3e7cced317a4a3b7a02aaf60f86e92ec9d49a3db7fbe7d280944e0c70"

# Task 3: build optimization comparison
fetch_image "docker.io/library/python:3.11" \
    "python_3.11.tar" \
    "8f23fe72b4c9c049aadd56dba0bcba440111635d3a548fad17750f932c483752"

# Task 4: forensics (alpine containers)
fetch_image "docker.io/library/alpine:3.18" \
    "alpine_3.18.tar" \
    "802c91d5298192c0f3a08101aeb5f9ade2992e22c9e27fa8b88eab82602550d0"

fetch_image "docker.io/library/alpine:3.19" \
    "alpine_3.19.tar" \
    "83b2b6703a620bf2e001ab57f7adc414d891787b3c59859b1b62909e48dd2242"

# Task 5: database migration
fetch_image "docker.io/library/postgres:13" \
    "postgres_13.tar" \
    "264e9dea325c61b96546c4065848e3ecaa85333b750506f783eced0a1830e37e"

fetch_image "docker.io/library/postgres:15" \
    "postgres_15.tar" \
    "d743cd41504b6e2a0699afb9af94eac4403e7b93a60b06fa92d9ef5732d06d58"

echo ""
echo "All assets verified."
