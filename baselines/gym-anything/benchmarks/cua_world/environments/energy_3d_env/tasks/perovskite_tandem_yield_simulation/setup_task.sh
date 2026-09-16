#!/bin/bash
echo "=== Setting up perovskite_tandem_yield_simulation task ==="

source /workspace/scripts/task_utils.sh

# Record task start time (for anti-gaming timestamp checks)
date +%s > /tmp/task_start_time.txt

# Define paths
USER_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$USER_DIR"
chown ga:ga "$USER_DIR"

SRC_FILE="/opt/energy3d_samples/solar-rack-array.ng3"
TARGET_FILE="$USER_DIR/solar-rack-array.ng3"

# Copy sample project
if [ -f "$SRC_FILE" ]; then
    cp "$SRC_FILE" "$TARGET_FILE"
    chown ga:ga "$TARGET_FILE"
    echo "Starter project loaded: $TARGET_FILE"
else
    echo "ERROR: Source file $SRC_FILE not found."
    exit 1
fi

# Ensure previous task artifacts are cleared
rm -f "$USER_DIR/high_efficiency_array.ng3"
rm -f "$USER_DIR/yield_graph.png"
rm -f "$USER_DIR/yield_report.txt"

# Launch Energy3D with the starter file
setup_energy3d_task "$TARGET_FILE"

echo "=== Task setup complete ==="