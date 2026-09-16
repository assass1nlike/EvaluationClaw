#!/usr/bin/env bash
YOURBENCH_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export YOURBENCH_ROOT
export UV_CACHE_DIR="$YOURBENCH_ROOT/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$YOURBENCH_ROOT/.python"
export UV_PROJECT_ENVIRONMENT="$YOURBENCH_ROOT/.venv"
export XDG_CACHE_HOME="$YOURBENCH_ROOT/.cache"
export HF_HOME="$YOURBENCH_ROOT/.cache/huggingface"
export TIKTOKEN_CACHE_DIR="$YOURBENCH_ROOT/.cache/tiktoken"
export TMPDIR="$YOURBENCH_ROOT/.tmp"
export PYTHONHASHSEED=42
export HF_HUB_DISABLE_TELEMETRY=1
mkdir -p "$TMPDIR" "$UV_CACHE_DIR"
