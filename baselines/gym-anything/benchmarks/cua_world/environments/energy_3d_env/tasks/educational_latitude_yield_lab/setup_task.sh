#!/bin/bash
echo "=== Setting up Educational Latitude Yield Lab task ==="

source /workspace/scripts/task_utils.sh

# Record task start time
date +%s > /tmp/task_start_time.txt

# Create working directory and clear any previous artifacts
mkdir -p /home/ga/Documents/Energy3D
rm -f /home/ga/Documents/Energy3D/latitude_lab_results.csv

# Prepare the specific sample file
STARTER_FILE="/home/ga/Documents/Energy3D/solar_array_starter.ng3"
cp /opt/energy3d_samples/solar-rack-array.ng3 "$STARTER_FILE"
chown ga:ga "$STARTER_FILE"

# Launch Energy3D with the starter file
echo "Launching Energy3D..."
setup_energy3d_task "$STARTER_FILE"

echo "=== Task setup complete ==="