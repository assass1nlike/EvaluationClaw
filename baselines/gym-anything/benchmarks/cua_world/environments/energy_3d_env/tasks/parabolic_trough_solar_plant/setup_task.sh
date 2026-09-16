#!/bin/bash
echo "=== Setting up parabolic_trough_solar_plant task ==="

source /workspace/scripts/task_utils.sh

# Record task start time (for anti-gaming verification)
date +%s > /tmp/task_start_time.txt
echo "Task start time recorded: $(cat /tmp/task_start_time.txt)"

# Clean up any previous task artifacts
TARGET_FILE="/home/ga/Documents/Energy3D/trough_plant.ng3"
rm -f "$TARGET_FILE" 2>/dev/null || true

# Ensure target directory exists
mkdir -p /home/ga/Documents/Energy3D
chown -R ga:ga /home/ga/Documents/Energy3D

# Launch Energy3D with a blank scene using the utility function
setup_energy3d_task ""

echo "=== Task setup complete ==="