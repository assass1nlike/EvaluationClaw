#!/bin/bash
echo "=== Setting up parabolic_trough_process_heat_design task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Ensure the target directory exists
mkdir -p /home/ga/Documents/Energy3D
chown -R ga:ga /home/ga/Documents

# Remove any pre-existing output files to ensure a clean state
rm -f /home/ga/Documents/Energy3D/trough_plant.ng3
rm -f /home/ga/Documents/Energy3D/thermal_yield.txt

# Record start time for anti-gaming verification
date +%s > /tmp/task_start_time.txt

# Launch Energy3D with an empty project
setup_energy3d_task ""

echo "=== Task setup complete ==="