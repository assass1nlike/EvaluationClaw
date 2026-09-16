#!/bin/bash
echo "=== Setting up residential_window_retrofit_analysis task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Define paths
USER_DIR="/home/ga/Documents/Energy3D"
SRC="/opt/energy3d_samples/building-passive-heating.ng3"
DST="$USER_DIR/building-passive-heating.ng3"

# Ensure user directory exists
mkdir -p "$USER_DIR"

# Clean any existing task artifacts
rm -f "$USER_DIR/window_retrofit.ng3"
rm -f "$USER_DIR/retrofit_report.txt"
rm -f "$USER_DIR/upgraded_analysis.png"
rm -f "$USER_DIR/baseline_analysis.png"

# Copy the real sample project to the user's working directory
if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found at $SRC"
    exit 1
fi
cp "$SRC" "$DST"
chown -R ga:ga "$USER_DIR" 2>/dev/null || true

# Record task start timestamp for anti-gaming checks
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Launch Energy3D with the starter file
setup_energy3d_task "$DST"

echo "=== Setup complete ==="