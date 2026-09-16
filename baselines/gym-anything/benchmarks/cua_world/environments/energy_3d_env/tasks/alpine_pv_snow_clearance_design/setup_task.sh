#!/bin/bash
echo "=== Setting up alpine_pv_snow_clearance_design task ==="
source /workspace/scripts/task_utils.sh || true

# Record task start time for anti-gaming verification
date +%s > /tmp/task_start_time.txt

SRC="/opt/energy3d_samples/solar-rack-array.ng3"
DST="/home/ga/Documents/Energy3D/solar-rack-array.ng3"
mkdir -p /home/ga/Documents/Energy3D

# Clean any existing outputs from previous runs
rm -f "/home/ga/Documents/Energy3D/alpine_snow_array.ng3"
rm -f "/home/ga/Documents/Energy3D/anchorage_yield.csv"
rm -f /tmp/task_result.json

# Copy fresh starter file
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Launch Energy3D with the starter file (handled by environment task_utils)
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="