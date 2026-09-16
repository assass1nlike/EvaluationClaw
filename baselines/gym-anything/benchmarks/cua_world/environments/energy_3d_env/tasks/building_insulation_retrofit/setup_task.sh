#!/bin/bash
echo "=== Setting up building_insulation_retrofit task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task start time for anti-gaming (must export/create files after this)
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Define paths
USER_DIR="/home/ga/Documents/Energy3D"
SRC="/opt/energy3d_samples/building-roof-insulation.ng3"
DST="$USER_DIR/building-roof-insulation.ng3"

# Ensure clean state
rm -f "$DST"
rm -f "$USER_DIR/retrofitted_building.ng3"
rm -f "$USER_DIR/retrofit_analysis.png"
mkdir -p "$USER_DIR"

# Copy the real sample data
if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

cp "$SRC" "$DST"
chown -R ga:ga "$USER_DIR"

echo "Task start timestamp: $(cat /tmp/task_start_time.txt)"
echo "Input file prepared: $DST"

# Launch Energy3D with the starter file using the utility
setup_energy3d_task "$DST"

echo "=== building_insulation_retrofit task setup complete ==="