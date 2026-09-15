ACA_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="$ACA_ROOT/.cache/uv"
export XDG_CACHE_HOME="$ACA_ROOT/.cache"
export XDG_CONFIG_HOME="$ACA_ROOT/.local/config"
export XDG_DATA_HOME="$ACA_ROOT/.local/share"
export XDG_STATE_HOME="$ACA_ROOT/.local/state"
export TMPDIR="$ACA_ROOT/.tmp"
export TIKTOKEN_CACHE_DIR="$ACA_ROOT/.cache/tiktoken"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PATH="$ACA_ROOT/.venv/bin:$PATH"
if [[ -f "$ACA_ROOT/.env" ]]; then
    set -a
    source "$ACA_ROOT/.env"
    set +a
fi
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME"
