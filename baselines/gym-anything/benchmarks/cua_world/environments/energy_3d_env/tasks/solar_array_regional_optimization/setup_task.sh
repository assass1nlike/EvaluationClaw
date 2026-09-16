#!/bin/bash
echo "=== Setting up solar_array_regional_optimization task ==="

# Source environment task utilities
source /workspace/scripts/task_utils.sh

# Define paths
SRC="/opt/energy3d_samples/solar-panel-tilt-angle.ng3"
DOCS_DIR="/home/ga/Documents/Energy3D"
STARTER_FILE="$DOCS_DIR/solar-panel-tilt-angle.ng3"
TARGET_FILE="$DOCS_DIR/phoenix-solar-array.ng3"

# Ensure clean state (remove previous task attempts)
rm -f "$TARGET_FILE"
mkdir -p "$DOCS_DIR"

# Copy the starter file to the working directory
if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

cp "$SRC" "$STARTER_FILE"
chown -R ga:ga "$DOCS_DIR"

# Record the start time for anti-gaming timestamp checks
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

echo "Starting Energy3D with $STARTER_FILE"

# Launch Energy3D with the starter file and take initial screenshot
setup_energy3d_task "$STARTER_FILE"

echo "=== Task setup complete ==="