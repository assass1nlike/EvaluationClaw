#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
exec "$YOURBENCH_ROOT/.venv/bin/python" "$YOURBENCH_ROOT/run.py" "$@"
