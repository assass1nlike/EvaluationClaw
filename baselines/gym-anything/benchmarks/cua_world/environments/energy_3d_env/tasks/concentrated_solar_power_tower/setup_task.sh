#!/bin/bash
echo "=== Setting up Concentrated Solar Power task ==="

source /workspace/scripts/task_utils.sh || true

TARGET_FILE="/home/ga/Documents/Energy3D/csp_las_vegas.ng3"
START_TS_FILE="/tmp/task_start_time.txt"

# Ensure the target directory exists
mkdir -p /home/ga/Documents/Energy3D
chown -R ga:ga /home/ga/Documents

# Clean up any existing file to ensure a clean slate
rm -f "$TARGET_FILE"

# Record the exact start time for anti-gaming verification
date +%s > "$START_TS_FILE"

# Start Energy3D with a blank project (no file argument)
echo "Launching Energy3D..."
setup_energy3d_task ""

echo "=== Setup complete ==="