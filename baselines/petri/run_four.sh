#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$PETRI_ROOT"
batch_dir="$PETRI_ROOT/results/four-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$batch_dir"
pids=()
ids=(07 08 09 13)
for id in "${ids[@]}"; do
  bash run.sh --instruction "inputs/requirement-$id.txt" \
    --auditor deepseek/deepseek-flash --target deepseek/deepseek-flash \
    --judge deepseek/deepseek-flash --base-url https://api.deepseek.com/beta \
    --max-turns 200 --thinking enabled --reasoning-effort high \
    --max-tokens 300000 --request-timeout 600 --time-limit 0 \
    --prefill-mode no-prefill \
    --output-dir "$batch_dir/requirement-$id" "$@" \
    > "$batch_dir/requirement-$id.console.log" 2>&1 &
  pids+=("$!")
done
echo "Batch: $batch_dir"
failed=0
for index in "${!pids[@]}"; do
  code=0
  wait "${pids[$index]}" || code=$?
  echo "${ids[$index]} $code" >> "$batch_dir/exit-codes.txt"
  echo "Requirement ${ids[$index]} exited: $code"
  if ((code != 0)); then failed=1; fi
done
exit "$failed"
