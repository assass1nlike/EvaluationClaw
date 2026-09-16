#!/bin/bash
echo "=== Setting up urban_solar_heat_map_analysis task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Set up user directories
USER_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$USER_DIR"
chown ga:ga "$USER_DIR"

# Define target paths
SRC="/opt/energy3d_samples/city-block.ng3"
DST="$USER_DIR/city-block.ng3"
TARGET_PROJ="$USER_DIR/city-block-boston-summer.ng3"
TARGET_IMG="$USER_DIR/boston_summer_heatmap.png"

# Remove target files if they exist to prevent gaming
rm -f "$TARGET_PROJ" "$TARGET_IMG" 2>/dev/null || true

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

# Copy the real starter project
cp "$SRC" "$DST"
chown ga:ga "$DST"

# Record task start timestamp for anti-gaming (file creation checks)
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt

# Launch Energy3D and open the starter file
setup_energy3d_task "$DST"

echo "=== Setup complete ==="