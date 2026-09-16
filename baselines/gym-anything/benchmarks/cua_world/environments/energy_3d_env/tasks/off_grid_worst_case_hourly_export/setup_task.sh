#!/bin/bash
echo "=== Setting up off_grid_worst_case_hourly_export task ==="

source /workspace/scripts/task_utils.sh

# Setup directories
mkdir -p /home/ga/Documents/Energy3D
chown -R ga:ga /home/ga/Documents/Energy3D

# Remove any existing artifacts that might give false positives
rm -f /home/ga/Documents/Energy3D/boston_winter.ng3
rm -f /home/ga/Documents/Energy3D/boston_dec21_hourly.csv

# Prepare starter file
SRC="/opt/energy3d_samples/solar-rack-array.ng3"
DST="/home/ga/Documents/Energy3D/solar-rack-array.ng3"

if [ -f "$SRC" ]; then
    cp "$SRC" "$DST"
    chown ga:ga "$DST"
else
    echo "WARNING: Source sample $SRC not found."
fi

# Record start time for anti-gaming
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt

# Launch Energy3D with the starter file
setup_energy3d_task "$DST"

echo "=== Setup complete ==="