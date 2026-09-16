#!/bin/bash
echo "=== Setting up ev_truck_canopy_upgrade task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils.sh"; exit 1; }

# Create user documents directory
USER_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$USER_DIR"

# Define files
SRC="/opt/energy3d_samples/solar-canopy.ng3"
DST="$USER_DIR/solar-canopy.ng3"
EXPANDED_FILE="$USER_DIR/ev_canopy_expanded.ng3"
SUMMARY_FILE="$USER_DIR/yield_summary.txt"

# Ensure clean slate
rm -f "$EXPANDED_FILE"
rm -f "$SUMMARY_FILE"
rm -f /tmp/ev_canopy_expanded.ng3
rm -f /tmp/task_result.json

if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

# Copy starter project
cp "$SRC" "$DST"
chown -R ga:ga "$USER_DIR" 2>/dev/null || true

# Record task start timestamp (anti-gaming)
date +%s > /tmp/task_start_time.txt

# Launch Energy3D with the starter file
echo "Launching Energy3D..."
setup_energy3d_task "$DST"

# Take initial screenshot for evidence
sleep 2
take_screenshot /tmp/task_initial.png

echo "=== ev_truck_canopy_upgrade task setup complete ==="