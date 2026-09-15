#!/usr/bin/env bash
set -euo pipefail
bash "$(dirname -- "${BASH_SOURCE[0]}")/run.sh" run \
    --scenario benchmark/specification_gaming/sg_01_compliance_checklist_gaming \
    --profile deepseek-flash \
    --no-interactive-design
