#!/bin/bash
echo "=== Setting up Tree Shading Impact task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Set timestamp for anti-gaming verification
date +%s > /tmp/task_start_time.txt

# Remove any existing output files from previous attempts
rm -f /home/ga/Documents/Energy3D/yield_current.csv
rm -f /home/ga/Documents/Energy3D/yield_year_20.csv
rm -f /home/ga/Documents/Energy3D/tree_shading_study.ng3

# Prepare the starter file
SRC="/opt/energy3d_samples/building-passive-heating.ng3"
DST="/home/ga/Documents/Energy3D/building-passive-heating.ng3"

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

echo "Starter file ready: $DST"

# Launch Energy3D with the starter file
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="