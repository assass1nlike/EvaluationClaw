#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$ACA_ROOT"
uv venv --python /usr/bin/python3.10 .venv
uv pip install --python .venv/bin/python -r local/requirements.lock
uv pip check --python .venv/bin/python
