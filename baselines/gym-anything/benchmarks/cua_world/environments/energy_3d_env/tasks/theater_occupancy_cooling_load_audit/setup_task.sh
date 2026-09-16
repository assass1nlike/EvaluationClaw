#!/bin/bash
echo "=== Setting up Theater Occupancy Cooling Load Audit task ==="

source /workspace/scripts/task_utils.sh

# Record task start time (for anti-gaming verification)
date +%s > /tmp/task_start_time.txt
echo "Task start time recorded: $(cat /tmp/task_start_time.txt)"

# Define paths
SRC_FILE="/opt/energy3d_samples/building-shape.ng3"
DOC_DIR="/home/ga/Documents/Energy3D"
START_FILE="$DOC_DIR/building_shape_starter.ng3"

# Ensure directory exists and clean up any previous artifacts
mkdir -p "$DOC_DIR"
rm -f "$DOC_DIR/occupied_theater.ng3"
rm -f "$DOC_DIR/cooling_audit.txt"

# Copy the real sample dataset
if [ ! -f "$SRC_FILE" ]; then
    echo "ERROR: Source sample file not found at $SRC_FILE"
    exit 1
fi
cp "$SRC_FILE" "$START_FILE"
chown -R ga:ga "$DOC_DIR"

# Launch Energy3D with the starter file
echo "Launching Energy3D..."
setup_energy3d_task "$START_FILE"

echo "=== Setup complete ==="