#!/bin/bash
echo "=== Setting up hot_climate_building_orientation task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="hot_climate_building_orientation"
SRC="/opt/energy3d_samples/building-orientation.ng3"
DST="/home/ga/Documents/Energy3D/building-orientation.ng3"
OUTPUT_PATH="/home/ga/Documents/Energy3D/phoenix_rotated.ng3"

# Record task start time for anti-gaming
date +%s > /tmp/task_start_time.txt

# Clean up any previous task artifacts
rm -f "$OUTPUT_PATH" 2>/dev/null || true

# Verify source file exists
if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found at $SRC"
    exit 1
fi

# Copy the starter file into place
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record initial file info
STARTER_SIZE=$(stat -c %s "$DST" 2>/dev/null || echo "0")
echo "$STARTER_SIZE" > /tmp/initial_file_size.txt

# Launch Energy3D with the starter file
echo "Launching Energy3D..."
setup_energy3d_task "$DST"

echo "=== Setup complete ==="