#!/bin/bash
echo "=== Setting up BIPV Facade Yield Analysis Task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Set up paths
DOC_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$DOC_DIR"

SRC="/opt/energy3d_samples/city-block.ng3"
START_DST="$DOC_DIR/city-block.ng3"
TARGET_NG3="$DOC_DIR/city_block_bipv.ng3"
TARGET_CSV="$DOC_DIR/bipv_yield.csv"
START_TS="/tmp/task_start_ts"

# Clean up any previous artifacts to prevent gaming
rm -f "$TARGET_NG3" "$TARGET_CSV" "$START_DST"

# Verify source exists
if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

# Copy starter project
cp "$SRC" "$START_DST"
chown ga:ga "$START_DST"

# Record task start timestamp for anti-gaming verification
date +%s > "$START_TS"
echo "Task start timestamp: $(cat $START_TS)"

# Launch Energy3D with the starter file and maximize
setup_energy3d_task "$START_DST"

echo "=== BIPV Facade task setup complete ==="