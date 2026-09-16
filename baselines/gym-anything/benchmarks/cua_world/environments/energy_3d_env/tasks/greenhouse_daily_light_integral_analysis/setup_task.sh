#!/bin/bash
echo "=== Setting up greenhouse_daily_light_integral_analysis task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="greenhouse_analysis"
SRC="/opt/energy3d_samples/building-shape.ng3"
DST="/home/ga/Documents/Energy3D/building-shape.ng3"
START_TS="/tmp/${TASK_NAME}_start_ts"

# Clean up any artifacts from previous runs
rm -f "$DST"
rm -f "/home/ga/Documents/Energy3D/greenhouse_design.ng3"
rm -f "/home/ga/Documents/Energy3D/winter_radiation_map.png"

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

# Ensure user directory exists and copy the starter file
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record the start timestamp to prevent "do nothing" spoofing
date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true
echo "Task start timestamp: $(cat $START_TS)"

# Launch Energy3D with the starter file, focus it, and maximize
setup_energy3d_task "$DST"

echo "=== greenhouse_daily_light_integral_analysis task setup complete ==="