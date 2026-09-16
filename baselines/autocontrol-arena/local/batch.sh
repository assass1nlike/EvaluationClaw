#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$ACA_ROOT"
run_dir="$1"
export AUTOCONTROL_ARENA_BATCH_UI=plain
export AUTOCONTROL_ARENA_RESULTS_DIR="$run_dir"
export AUTOCONTROL_ARENA_RUNTIME_ENV_DIR="$run_dir/runtime_envs"
trap 'code=$?; printf "%s\n" "$code" > "$run_dir/exit_code"; date -u +%FT%TZ > "$run_dir/finished_at"' EXIT
date -u +%FT%TZ > "$run_dir/started_at"
bash local/run.sh batch --file "$run_dir/batch.json" --output-dir "$run_dir" --yes
