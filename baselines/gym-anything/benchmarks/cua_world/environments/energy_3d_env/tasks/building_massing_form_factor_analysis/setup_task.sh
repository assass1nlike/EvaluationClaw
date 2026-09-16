#!/bin/bash
echo "=== Setting up building_massing_form_factor_analysis task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="building_massing_form_factor_analysis"
SRC="/opt/energy3d_samples/building-shape.ng3"
DST="/home/ga/Documents/Energy3D/building-shape.ng3"
REPORT_FILE="/home/ga/Documents/Energy3D/massing_report.txt"

# Record task start time for anti-gaming (file creation check)
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Clean stale artifacts
rm -f "$REPORT_FILE"

# Prepare the starter file
if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown -R ga:ga "$(dirname "$DST")" 2>/dev/null || true

# Launch Energy3D (using the helper from task_utils.sh)
setup_energy3d_task "$DST"

echo "=== building_massing_form_factor_analysis task setup complete ==="