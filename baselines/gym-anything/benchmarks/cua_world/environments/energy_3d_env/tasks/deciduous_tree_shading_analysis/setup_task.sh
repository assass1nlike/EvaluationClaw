#!/bin/bash
echo "=== Setting up deciduous_tree_shading_analysis task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="deciduous_tree_shading_analysis"
SRC="/opt/energy3d_samples/building-passive-heating.ng3"
DST="/home/ga/Documents/Energy3D/building_starter.ng3"
OUTPUT_NG3="/home/ga/Documents/Energy3D/shaded_building.ng3"
OUTPUT_CSV="/home/ga/Documents/Energy3D/summer_analysis.csv"
START_TS_FILE="/tmp/${TASK_NAME}_start_ts"

# Ensure clean slate for outputs
rm -f "$OUTPUT_NG3" 2>/dev/null || true
rm -f "$OUTPUT_CSV" 2>/dev/null || true

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record task start timestamp for anti-gaming verification
TASK_START=$(date +%s)
echo "$TASK_START" > "$START_TS_FILE"
chown ga:ga "$START_TS_FILE" 2>/dev/null || true
echo "Task start timestamp: $TASK_START"

# Launch Energy3D with the starter file
setup_energy3d_task "$DST"

echo "=== deciduous_tree_shading_analysis task setup complete ==="