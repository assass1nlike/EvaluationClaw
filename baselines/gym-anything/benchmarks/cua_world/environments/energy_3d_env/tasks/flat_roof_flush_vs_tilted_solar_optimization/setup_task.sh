#!/bin/bash
echo "=== Setting up flat_roof_flush_vs_tilted_solar_optimization task ==="

source /workspace/scripts/task_utils.sh

# Record task start time for anti-gaming (file creation timestamp check)
date +%s > /tmp/task_start_time.txt

# Clean up any previous attempts to ensure clean slate
rm -rf /home/ga/Documents/Energy3D
mkdir -p /home/ga/Documents/Energy3D
chown -R ga:ga /home/ga/Documents/Energy3D

# Launch Energy3D
echo "Killing existing instances..."
kill_energy3d 2>/dev/null || true

echo "Launching Energy3D..."
launch_energy3d "" 120
sleep 10

echo "Dismissing startup dialogs..."
dismiss_dialogs 4

echo "Maximizing window..."
maximize_energy3d
sleep 2

# Take initial state evidence screenshot
take_screenshot /tmp/task_initial.png

echo "=== Task setup complete ==="