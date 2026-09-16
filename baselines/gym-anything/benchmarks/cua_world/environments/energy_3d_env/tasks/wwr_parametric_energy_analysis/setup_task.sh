#!/bin/bash
set -e
echo "=== Setting up wwr_parametric_energy_analysis task ==="

source /workspace/scripts/task_utils.sh

# Record task start time (for anti-gaming verification)
date +%s > /tmp/task_start_time.txt

USER_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$USER_DIR"

# Set up the specific real-data starter project
SRC="/opt/energy3d_samples/building-passive-heating.ng3"
DST="$USER_DIR/building_starter.ng3"

# Clean up any previous task artifacts
rm -f "$USER_DIR/chicago_wwr_60.ng3"
rm -f "$USER_DIR/wwr_results.csv"

# Copy and set ownership
if [ -f "$SRC" ]; then
    cp "$SRC" "$DST"
    chown ga:ga "$DST"
else
    echo "ERROR: Could not find source sample $SRC"
    exit 1
fi

# Launch Energy3D with the starter project and maximize window
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="