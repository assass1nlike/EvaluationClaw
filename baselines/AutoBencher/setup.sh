#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export UV_CACHE_DIR="$PWD/.cache/uv"
export PIP_CACHE_DIR="$PWD/.cache/pip"
export TMPDIR="$PWD/.cache/tmp"
mkdir -p "$TMPDIR"
if [ ! -x .tools/bin/uv ]; then
  python -m pip install --target .tools uv==0.12.15
fi
if [ ! -d upstream ]; then
  git clone https://github.com/XiangLi1999/AutoBencher.git upstream
  git -C upstream checkout a05be9f1f776e4658de77e28c6bf22606cea01ab
fi
if ! git -C upstream apply --reverse --check ../patches/wikipedia-search-cycle.patch 2>/dev/null; then
  if ! git -C upstream apply --reverse --check ../patches/wikipedia-search-encoding.patch 2>/dev/null; then
    if ! git -C upstream apply --reverse --check ../patches/wikipedia-retries.patch 2>/dev/null; then
      if ! git -C upstream apply --reverse --check ../patches/wikipedia-user-agent.patch 2>/dev/null; then
        git -C upstream apply ../patches/wikipedia-user-agent.patch
      fi
      git -C upstream apply ../patches/wikipedia-retries.patch
    fi
    git -C upstream apply ../patches/wikipedia-search-encoding.patch
  fi
  git -C upstream apply ../patches/wikipedia-search-cycle.patch
fi
if [ ! -x .venv/bin/python ]; then
  .tools/bin/uv venv --python /usr/bin/python3.10 .venv
fi
.tools/bin/uv pip install --python .venv/bin/python \
  --index-url https://pypi.org/simple \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --index-strategy unsafe-best-match -r requirements.lock
