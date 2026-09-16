#!/bin/bash
set -e
echo "=== Setting up utility_interconnection_peak_vs_energy task ==="

# Source Energy3D task utilities
source /workspace/scripts/task_utils.sh

# Define variables
TASK_NAME="utility_interconnection_peak_vs_energy"
SRC_FILE="/opt/energy3d_samples/solar-rack-array.ng3"
USER_DIR="/home/ga/Documents/Energy3D"
DEST_FILE="${USER_DIR}/solar-rack-array.ng3"
START_TS_FILE="/tmp/task_start_time.txt"

# Record start time for anti-gaming checks
date +%s > "$START_TS_FILE"

# Prepare user directory and copy the exact starting file
mkdir -p "$USER_DIR"
rm -f "$DEST_FILE"
rm -f "${USER_DIR}/interconnection_report.txt"

if [ ! -f "$SRC_FILE" ]; then
    echo "ERROR: Source sample not found: $SRC_FILE"
    exit 1
fi

cp "$SRC_FILE" "$DEST_FILE"
chown -R ga:ga "$USER_DIR"

# Launch Energy3D with the specific starting project
echo "Launching Energy3D..."
setup_energy3d_task "$DEST_FILE"

# Wait a moment for UI to fully settle, then ensure we have the screenshot
sleep 2
echo "Capturing initial state..."
DISPLAY=:1 scrot /tmp/task_initial.png 2>/dev/null || \
    DISPLAY=:1 import -window root /tmp/task_initial.png 2>/dev/null || true

echo "=== utility_interconnection_peak_vs_energy task setup complete ==="