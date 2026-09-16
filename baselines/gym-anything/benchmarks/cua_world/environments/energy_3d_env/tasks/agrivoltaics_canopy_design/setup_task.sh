#!/bin/bash
echo "=== Setting up Agrivoltaics Canopy Design task ==="

# Source Energy3D task utilities
source /workspace/scripts/task_utils.sh

USER_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$USER_DIR"

# Source file from real sample dataset
SRC="/opt/energy3d_samples/solar-rack-array-row-spacing.ng3"
DST="$USER_DIR/solar-rack-array-row-spacing.ng3"

if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

# Copy sample project into user's working directory
cp "$SRC" "$DST"
chown ga:ga "$DST"

# Clean up any potential artifacts from previous runs
rm -f "$USER_DIR/agrivoltaics_array.ng3"
rm -f "$USER_DIR/agrivoltaics_yield.csv"

# Record task start time for anti-gaming (file modification checks)
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Launch Energy3D with the copied sample file
# (This utility handles launching, waiting, maximizing, dismissing dialogs, and taking initial screenshot)
setup_energy3d_task "$DST"

echo "=== Agrivoltaics Canopy Design task setup complete ==="