#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
uv sync --project "$PETRI_ROOT/upstream" --frozen --python 3.12 --no-dev
uv pip install --python "$PETRI_ROOT/.venv/bin/python" socksio==1.0.0 pytest==8.4.1 pytest-asyncio==1.1.0
