#!/bin/bash
echo "=== Setting up winter_solstice_tilt_optimization task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="winter_solstice_tilt_optimization"
SRC="/opt/energy3d_samples/solar-panel-tilt-angle.ng3"
USER_DIR="/home/ga/Documents/Energy3D"
DST="$USER_DIR/solar-panel-tilt-angle.ng3"
EXPECTED_NG3="$USER_DIR/winter_optimized.ng3"
EXPECTED_REPORT="$USER_DIR/winter_report.txt"
START_TS="/tmp/${TASK_NAME}_start_ts"

# Ensure clean state for output files
rm -f "$EXPECTED_NG3"
rm -f "$EXPECTED_REPORT"

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

# Prepare user directory and copy starter file
mkdir -p "$USER_DIR"
cp "$SRC" "$DST"
chown -R ga:ga "$USER_DIR"

# Record anti-gaming timestamp
date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true
echo "Task start timestamp: $(cat $START_TS)"

# Launch Energy3D with the starter file
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="