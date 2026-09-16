#!/bin/bash
echo "=== Setting up parabolic_dish_farm_yield_comparison task ==="

source /workspace/scripts/task_utils.sh

# Target file paths
DST="/home/ga/Documents/Energy3D/desert_plot.ng3"
FINAL_NG3="/home/ga/Documents/Energy3D/dish_farm_final.ng3"
FINAL_TXT="/home/ga/Documents/Energy3D/yield_comparison.txt"

# Clean previous artifacts
rm -f "$DST" "$FINAL_NG3" "$FINAL_TXT"

# Provide starter file - we use solar-rack-array as a base and instruct agent to clear it
SRC="/opt/energy3d_samples/solar-rack-array.ng3"
if [ ! -f "$SRC" ]; then
    echo "ERROR: Starter file $SRC not found"
    exit 1
fi

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST"

# Timestamp for anti-gaming checks
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt

# Launch Energy3D and maximize window
setup_energy3d_task "$DST"

# Take initial screenshot showing the loaded environment
echo "Capturing initial state..."
sleep 1
DISPLAY=:1 scrot /tmp/task_initial.png 2>/dev/null || \
    DISPLAY=:1 import -window root /tmp/task_initial.png 2>/dev/null || true

echo "=== Task setup complete ==="