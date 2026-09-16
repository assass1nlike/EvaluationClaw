#!/bin/bash
echo "=== Setting up parabolic_dish_repowering_upgrade task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Paths
SRC="/opt/energy3d_samples/solar-rack-array.ng3"
DST_DIR="/home/ga/Documents/Energy3D"
DST_FILE="$DST_DIR/solar-rack-array.ng3"
TARGET_OUTPUT="$DST_DIR/dish_array_upgrade.ng3"

# Record task start time for anti-gaming (checking file modifications)
date +%s > /tmp/task_start_time.txt

# Clean up any potential artifacts from previous runs
rm -f "$TARGET_OUTPUT" 2>/dev/null || true
rm -f "$DST_FILE" 2>/dev/null || true
rm -f /home/ga/dish_array_upgrade.ng3 2>/dev/null || true

# Prepare starter file
mkdir -p "$DST_DIR"
if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

cp "$SRC" "$DST_FILE"
chown -R ga:ga "$DST_DIR"

echo "Starter file ready: $DST_FILE"

# Launch Energy3D with the starter file (handled by task_utils.sh)
setup_energy3d_task "$DST_FILE"

echo "=== Setup complete ==="