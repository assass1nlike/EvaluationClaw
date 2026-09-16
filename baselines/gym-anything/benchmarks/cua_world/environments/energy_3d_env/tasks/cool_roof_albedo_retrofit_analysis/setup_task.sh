#!/bin/bash
echo "=== Setting up cool_roof_albedo_retrofit_analysis task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="cool_roof_albedo_retrofit_analysis"
SRC="/opt/energy3d_samples/building-shape.ng3"
USER_DIR="/home/ga/Documents/Energy3D"
DST="$USER_DIR/building-shape.ng3"
START_TS="/tmp/${TASK_NAME}_start_ts"

# Ensure clean state to prevent gaming
rm -f "$USER_DIR/cool_roof_optimized.ng3"
rm -f "$USER_DIR/cooling_savings.txt"
rm -f /tmp/task_result.json

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

mkdir -p "$USER_DIR"
cp "$SRC" "$DST"
chown -R ga:ga "$USER_DIR"

# Record anti-gaming timestamps
date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true
echo "Task start timestamp: $(cat $START_TS)"

# Launch Energy3D with the starter file
setup_energy3d_task "$DST"

echo "=== cool_roof_albedo_retrofit_analysis task setup complete ==="