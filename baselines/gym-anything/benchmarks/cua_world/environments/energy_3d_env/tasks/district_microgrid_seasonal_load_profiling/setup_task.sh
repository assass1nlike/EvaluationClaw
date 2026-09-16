#!/bin/bash
# Setup script for district_microgrid_seasonal_load_profiling
echo "=== Setting up district microgrid profiling task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="district_microgrid_seasonal_load_profiling"
SRC="/opt/energy3d_samples/city-block.ng3"
DOC_DIR="/home/ga/Documents/Energy3D"
DST="$DOC_DIR/city-block.ng3"
START_TS="/tmp/${TASK_NAME}_start_ts"

# Clean up any previous runs
rm -f "$DOC_DIR/houston_microgrid_august.csv"
rm -f "$DOC_DIR/houston_microgrid_january.csv"
rm -f "$DOC_DIR/houston_microgrid_district.ng3"
rm -f "$DST"

# Ensure document directory exists
mkdir -p "$DOC_DIR"

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

# Copy starter project
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record the start timestamp
date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true
echo "Task start timestamp: $(cat $START_TS)"

# Launch Energy3D with the starter file
setup_energy3d_task "$DST"

echo "=== Setup complete ==="