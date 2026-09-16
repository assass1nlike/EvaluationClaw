#!/bin/bash
echo "=== Setting up high_wind_landscape_solar_array_redesign task ==="

source /workspace/scripts/task_utils.sh

# Record task start time for anti-gaming
date +%s > /tmp/task_start_time.txt

# Define paths
USER_DIR="/home/ga/Documents/Energy3D"
SRC="/opt/energy3d_samples/solar-rack-array.ng3"
DST="$USER_DIR/solar_array_starter.ng3"
TARGET_NG3="$USER_DIR/miami_landscape_array.ng3"
TARGET_CSV="$USER_DIR/miami_annual_yield.csv"

# Ensure user directory exists
mkdir -p "$USER_DIR"

# Clean up any potential previous task artifacts
rm -f "$TARGET_NG3" "$TARGET_CSV" 2>/dev/null || true

# Check if sample source exists
if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found at $SRC"
    exit 1
fi

# Copy starter project into workspace
cp "$SRC" "$DST"
chown ga:ga "$DST"

# Launch Energy3D cleanly with the starter file
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="