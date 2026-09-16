#!/bin/bash
echo "=== Setting up aviation_hangar_solar_yield_pruning task ==="

# Source utilities for finding and controlling Energy3D window
source /workspace/scripts/task_utils.sh || { echo "WARNING: Failed to source task_utils"; }

TASK_NAME="aviation_hangar_solar_yield_pruning"
# Use the solar canopy example as our stand-in for the "barrel vault hangar" 
# since it features a continuous surface covered with solar panels.
SRC="/opt/energy3d_samples/solar-canopy.ng3"
DST="/home/ga/Documents/Energy3D/hangar_baseline.ng3"
START_TS="/tmp/${TASK_NAME}_start_ts"

# Clean up any artifacts from previous runs
rm -f "$DST" 
rm -f "/home/ga/Documents/Energy3D/hangar_optimized.ng3"
rm -f "/home/ga/Documents/Energy3D/optimized_yield.csv"

if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

# Ensure user directory exists
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record task start time
date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true

echo "Starter file prepared at $DST"
echo "Task start timestamp: $(cat $START_TS)"

# Launch Energy3D natively via the shared utility function, passing the file to open
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="