#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$ACA_ROOT"
exec "$ACA_ROOT/.venv/bin/python" -m local.run "$@"
