#!/bin/bash
echo "=== Setting up supermarket_rtu_shading_solar_layout task ==="

source /workspace/scripts/task_utils.sh

# Record task start time
date +%s > /tmp/task_start_time.txt

# Create Energy3D user documents folder
mkdir -p /home/ga/Documents/Energy3D
chown ga:ga /home/ga/Documents/Energy3D

# Remove any artifacts from previous runs
rm -f /home/ga/Documents/Energy3D/supermarket_rtu_layout.ng3
rm -f /home/ga/Documents/Energy3D/supermarket_yield.csv

# Launch Energy3D without a specific file (starts a blank scene)
setup_energy3d_task ""

echo "=== Task setup complete ==="