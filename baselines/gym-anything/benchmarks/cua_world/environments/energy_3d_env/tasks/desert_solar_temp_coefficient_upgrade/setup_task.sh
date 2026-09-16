#!/bin/bash
echo "=== Setting up desert_solar_temp_coefficient_upgrade task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="desert_solar_temp_coefficient_upgrade"
SRC="/opt/energy3d_samples/solar-rack-array.ng3"
USER_DIR="/home/ga/Documents/Energy3D"
DST="$USER_DIR/solar-rack-array.ng3"
EXPECTED_OUT="$USER_DIR/hjt_upgrade_phoenix.ng3"
EXPECTED_REPORT="$USER_DIR/yield_report.txt"

# Record task start time for anti-gaming
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Clean stale artifacts
rm -f "$EXPECTED_OUT" 2>/dev/null || true
rm -f "$EXPECTED_REPORT" 2>/dev/null || true
rm -f "$DST" 2>/dev/null || true

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

mkdir -p "$USER_DIR"
cp "$SRC" "$DST"
chown -R ga:ga "$USER_DIR" 2>/dev/null || true

# Launch Energy3D with the starter file
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="