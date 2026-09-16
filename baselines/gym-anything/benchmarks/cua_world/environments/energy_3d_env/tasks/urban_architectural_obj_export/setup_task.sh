#!/bin/bash
echo "=== Setting up urban_architectural_obj_export task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="urban_architectural_obj_export"
SRC="/opt/energy3d_samples/city-block.ng3"
START_DIR="/home/ga/Documents/Energy3D"
DST="${START_DIR}/city-block.ng3"
EXPECTED_OBJ="${START_DIR}/proposed_city_block.obj"
EXPECTED_NG3="${START_DIR}/proposed_city_block.ng3"
START_TS="/tmp/task_start_time.txt"

# Ensure clean directory and remove potential stale outputs
mkdir -p "$START_DIR"
rm -f "$EXPECTED_OBJ" "$EXPECTED_NG3" "${START_DIR}/proposed_city_block.mtl"

# Copy original sample
if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi
cp "$SRC" "$DST"
chown -R ga:ga "$START_DIR" 2>/dev/null || true

# Record start time for anti-gaming verification
date +%s > "$START_TS"
echo "Task start timestamp: $(cat $START_TS)"

# Launch Energy3D with the starter file using standard util
setup_energy3d_task "$DST"

echo "=== urban_architectural_obj_export task setup complete ==="