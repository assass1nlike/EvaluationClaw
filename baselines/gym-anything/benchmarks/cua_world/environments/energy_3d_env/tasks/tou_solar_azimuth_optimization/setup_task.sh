#!/bin/bash
echo "=== Setting up Time-of-Use Azimuth Optimization Task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task start time for anti-gaming checks
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Define paths
SRC_SAMPLE="/opt/energy3d_samples/solar-panel-azimuth-angle.ng3"
USER_DIR="/home/ga/Documents/Energy3D"
TARGET_FILE="$USER_DIR/solar-panel-azimuth-angle.ng3"
EXPECTED_CSV="$USER_DIR/west_facing_yield.csv"
EXPECTED_NG3="$USER_DIR/tou_optimized.ng3"

# Clean up any potential stale files from previous runs
rm -f "$EXPECTED_CSV"
rm -f "$EXPECTED_NG3"
rm -f /tmp/west_facing_yield.csv

# Ensure the user directory exists
mkdir -p "$USER_DIR"

# Copy the sample file into place
if [ -f "$SRC_SAMPLE" ]; then
    cp "$SRC_SAMPLE" "$TARGET_FILE"
    chown -R ga:ga "$USER_DIR"
    echo "Starter file prepared at: $TARGET_FILE"
else
    echo "ERROR: Missing required sample file: $SRC_SAMPLE"
    exit 1
fi

# Launch Energy3D with the target file
echo "Launching Energy3D..."
setup_energy3d_task "$TARGET_FILE"

echo "=== Task Setup Complete ==="