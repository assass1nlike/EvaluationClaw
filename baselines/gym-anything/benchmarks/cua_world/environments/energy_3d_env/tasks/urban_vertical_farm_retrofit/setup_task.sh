#!/bin/bash
echo "=== Setting up urban_vertical_farm_retrofit task ==="

source /workspace/scripts/task_utils.sh

# Record task start time (for anti-gaming verification)
date +%s > /tmp/task_start_time.txt

# Ensure user document directory exists
mkdir -p /home/ga/Documents/Energy3D
chown -R ga:ga /home/ga/Documents/Energy3D

# Remove any existing output file to ensure a clean slate
rm -f /home/ga/Documents/Energy3D/vertical_farm_retrofit.ng3
rm -f /tmp/task_result.json

# Launch Energy3D blank (no file specified)
setup_energy3d_task ""

echo "=== Task setup complete ==="