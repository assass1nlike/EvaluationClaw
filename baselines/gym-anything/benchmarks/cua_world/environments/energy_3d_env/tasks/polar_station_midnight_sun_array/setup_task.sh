#!/bin/bash
echo "=== Setting up polar_station_midnight_sun_array task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task start time for anti-gaming (verification of modifications)
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Define paths
SRC="/opt/energy3d_samples/building-shape.ng3"
DST="/home/ga/Documents/Energy3D/polar_base.ng3"
SOLVED_DST="/home/ga/Documents/Energy3D/polar_base_solved.ng3"
CSV_DST="/home/ga/Documents/Energy3D/midnight_sun_yield.csv"

# Clean any existing artifacts from previous runs
rm -f "$DST" "$SOLVED_DST" "$CSV_DST"

# Prepare starting project
if [ -f "$SRC" ]; then
    mkdir -p "$(dirname "$DST")"
    cp "$SRC" "$DST"
    chown ga:ga "$DST"
    echo "Copied starter base: $DST"
else
    echo "WARNING: source sample $SRC not found. Task may start empty."
fi

# Launch Energy3D with the base project
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="