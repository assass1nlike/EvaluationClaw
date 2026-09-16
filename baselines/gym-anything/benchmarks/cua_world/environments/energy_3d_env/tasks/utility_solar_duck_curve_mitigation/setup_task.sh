#!/bin/bash
echo "=== Setting up utility_solar_duck_curve_mitigation task ==="

# Source task utilities
source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task start time (for anti-gaming timestamps)
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Prepare the starter file
USER_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$USER_DIR"
chown ga:ga "$USER_DIR" 2>/dev/null || true

SRC="/opt/energy3d_samples/solar-rack-array.ng3"
DST="$USER_DIR/duck_curve_starter.ng3"

# Remove any existing output artifacts
rm -f "$USER_DIR/duck_curve_mitigated.ng3"
rm -f "$USER_DIR/screenshot_daily_yield.png"
rm -f "$USER_DIR/profile_comparison.txt"
rm -f "$DST"

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Launch Energy3D with the starter file
echo "Launching Energy3D..."
setup_energy3d_task "$DST"

# Take initial screenshot as proof of clean state
sleep 2
take_screenshot /tmp/task_initial_state.png

echo "=== Setup complete ==="