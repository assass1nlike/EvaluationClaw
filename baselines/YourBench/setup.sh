#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$YOURBENCH_ROOT"
revision=46807647f99bd954747257a3db6a31a12f50b820
if [[ ! -d upstream/.git ]]; then
    git clone https://github.com/huggingface/yourbench.git upstream
    git -C upstream checkout --detach "$revision"
fi
test "$(git -C upstream rev-parse HEAD)" = "$revision"
uv python install --no-bin 3.12.13
uv sync --project upstream --frozen --python "$UV_PYTHON_INSTALL_DIR/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12"
