# Source this file in Bash before host-side infrastructure checks.
GYM_ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export VIRTUAL_ENV="$GYM_ROOT/.venv"
export PATH="$VIRTUAL_ENV/bin:$GYM_ROOT/local/runtime/tools:$PATH"
export GYM_VM_UPSTREAM_PROXY_PORT=17891
export DISABLE_AUTOUPDATER=1
export PYTHONHASHSEED=42
