#!/bin/bash
echo "=== Setting up Multi-City ESG Carbon Offset Comparison task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Define paths
SRC="/opt/energy3d_samples/solar-rack-array.ng3"
DST_DIR="/home/ga/Documents/Energy3D"
DST_FILE="$DST_DIR/solar-rack-array.ng3"
OUTPUT_FILE="$DST_DIR/esg_location_report.csv"
START_TS="/tmp/task_start_time.txt"

# Clean up any existing state
rm -f "$OUTPUT_FILE"
rm -f "$DST_FILE"
rm -f /tmp/esg_location_report.csv
rm -f /tmp/task_result.json

# Copy the real sample project
mkdir -p "$DST_DIR"
if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi
cp "$SRC" "$DST_FILE"
chown -R ga:ga "$DST_DIR"

# Record the start time for anti-gaming
date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true

# Launch Energy3D with the starter file and take initial screenshot
setup_energy3d_task "$DST_FILE"

echo "=== Task setup complete ==="