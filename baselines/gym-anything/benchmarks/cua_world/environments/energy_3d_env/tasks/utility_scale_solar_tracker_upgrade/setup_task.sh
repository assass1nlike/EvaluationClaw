#!/bin/bash
echo "=== Setting up utility_scale_solar_tracker_upgrade task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="utility_scale_solar_tracker_upgrade"
SRC="/opt/energy3d_samples/solar-rack-array.ng3"
DST_DIR="/home/ga/Documents/Energy3D"
DST="$DST_DIR/solar-rack-array.ng3"
TARGET_FILE="$DST_DIR/phoenix_hsat_array.ng3"
START_TS="/tmp/${TASK_NAME}_start_ts"

# Clean any previous artifacts
rm -f "$TARGET_FILE" 2>/dev/null || true

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

mkdir -p "$DST_DIR"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record start time for anti-gaming verification
date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true

# Launch Energy3D with the starter file
setup_energy3d_task "$DST"

echo "=== utility_scale_solar_tracker_upgrade task setup complete ==="