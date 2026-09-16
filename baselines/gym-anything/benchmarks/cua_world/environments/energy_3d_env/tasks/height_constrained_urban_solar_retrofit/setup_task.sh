#!/bin/bash
echo "=== Setting up height_constrained_urban_solar_retrofit task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="height_constrained_urban_solar_retrofit"
SRC="/opt/energy3d_samples/solar-rack-array-row-spacing.ng3"
DST="/home/ga/Documents/Energy3D/solar-rack-array-row-spacing.ng3"
START_TS="/tmp/${TASK_NAME}_start_ts"

# Clean any existing outputs to ensure clean state
rm -f "$DST"
rm -f "/home/ga/Documents/Energy3D/low_profile_array.ng3"
rm -f "/home/ga/Documents/Energy3D/yield_report.txt"

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record precise start time for anti-gaming verification
date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true
echo "Task start timestamp: $(cat $START_TS)"

# Launch Energy3D with the starter file and take initial screenshot
setup_energy3d_task "$DST"

echo "=== Setup complete ==="