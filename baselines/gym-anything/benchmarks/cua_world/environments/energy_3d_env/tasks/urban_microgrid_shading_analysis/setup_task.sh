#!/bin/bash
echo "=== Setting up urban_microgrid_shading_analysis task ==="

# Source shared utilities
source /workspace/scripts/task_utils.sh

# Record task start time (for anti-gaming timestamp checks)
date +%s > /tmp/task_start_time.txt

# Ensure the sample file is placed in the user's Documents directory
SRC="/opt/energy3d_samples/city-block.ng3"
DST="/home/ga/Documents/Energy3D/city-block.ng3"
TARGET_OUTPUT="/home/ga/Documents/Energy3D/chicago_microgrid.ng3"

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown -R ga:ga "/home/ga/Documents/Energy3D"

# Remove any existing output file to ensure a clean state
rm -f "$TARGET_OUTPUT" 2>/dev/null || true

# Launch Energy3D (open to a blank scene as designed)
echo "Launching Energy3D..."
kill_energy3d
launch_energy3d "" 90

# Wait for application to stabilize
sleep 8

# Dismiss dialogs and maximize
dismiss_dialogs 4
maximize_energy3d
sleep 2

# Take initial screenshot to prove starting state
take_screenshot /tmp/task_initial.png

echo "=== Task setup complete ==="