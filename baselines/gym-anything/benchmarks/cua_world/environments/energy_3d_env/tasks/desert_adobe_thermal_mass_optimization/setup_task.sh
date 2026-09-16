#!/bin/bash
echo "=== Setting up desert_adobe_thermal_mass_optimization task ==="

# Source utilities
source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="desert_adobe_thermal_mass_optimization"
SRC="/opt/energy3d_samples/building-passive-heating.ng3"
DST_DIR="/home/ga/Documents/Energy3D"
DST="$DST_DIR/building-passive-heating.ng3"

# Ensure clean directory and remove any stale artifacts from previous runs
mkdir -p "$DST_DIR"
rm -f "$DST_DIR/baseline_wood_frame.csv" 2>/dev/null
rm -f "$DST_DIR/adobe_thermal_mass.csv" 2>/dev/null
rm -f "$DST_DIR/adobe_house_design.ng3" 2>/dev/null

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

# Copy the real starter project
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record task start timestamp for anti-gaming checks
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true
echo "Task start timestamp: $(cat /tmp/task_start_time.txt)"

# Launch Energy3D and set up the window
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="