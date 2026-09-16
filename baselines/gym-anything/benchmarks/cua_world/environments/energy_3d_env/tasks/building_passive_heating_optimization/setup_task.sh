#!/bin/bash
echo "=== Setting up building_passive_heating_optimization task ==="

source /workspace/scripts/task_utils.sh

# Record task start time (for anti-gaming verification)
date +%s > /tmp/task_start_time.txt

# Set up paths
USER_DIR="/home/ga/Documents/Energy3D"
SRC_FILE="/opt/energy3d_samples/building-passive-heating.ng3"
STARTER_FILE="$USER_DIR/building-passive-heating.ng3"

mkdir -p "$USER_DIR"
rm -f "$USER_DIR/jan15_energy_load.csv"
rm -f "$USER_DIR/optimized_passive_heating.ng3"

# Copy original file to user directory
if [ -f "$SRC_FILE" ]; then
    cp "$SRC_FILE" "$STARTER_FILE"
    chown ga:ga "$STARTER_FILE"
else
    echo "ERROR: Source file $SRC_FILE not found!"
    exit 1
fi

# Record original file size (to verify the agent actually made changes to the saved project)
ORIGINAL_SIZE=$(stat -c%s "$STARTER_FILE" 2>/dev/null || echo "0")
echo "$ORIGINAL_SIZE" > /tmp/original_ng3_size.txt

# Launch Energy3D with the starter file
echo "Launching Energy3D..."
setup_energy3d_task "$STARTER_FILE"

echo "=== Task setup complete ==="