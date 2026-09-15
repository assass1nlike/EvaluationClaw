#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
export PYTHONHASHSEED=42
cd "$PETRI_ROOT"
exec "$PETRI_ROOT/.venv/bin/python" run.py "$@"
