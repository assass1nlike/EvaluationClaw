#!/bin/bash
echo "=== Setting up floatovoltaics_yield_simulation task ==="

source /workspace/scripts/task_utils.sh

# Record task start time for anti-gaming (file creation timestamps)
date +%s > /tmp/task_start_time.txt

# Create the working directory
mkdir -p /home/ga/Documents/Energy3D
chown ga:ga /home/ga/Documents/Energy3D

# Use an existing sample with a large foundation to act as the reservoir base
cp /opt/energy3d_samples/solar-rack-array.ng3 /home/ga/Documents/Energy3D/reservoir_base.ng3
chown ga:ga /home/ga/Documents/Energy3D/reservoir_base.ng3

# Clean up any potential previous outputs to avoid false positives
rm -f /home/ga/Documents/Energy3D/fpv_yield.csv
rm -f /home/ga/Documents/Energy3D/fpv_design.ng3

# Launch Energy3D with our targeted initial state file
setup_energy3d_task "/home/ga/Documents/Energy3D/reservoir_base.ng3"

echo "=== Setup complete ==="