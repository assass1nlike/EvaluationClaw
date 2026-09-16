#!/bin/bash
echo "=== Setting up ASHRAE Envelope Compliance Upgrade task ==="

# Source utility functions
source /workspace/scripts/task_utils.sh

TASK_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$TASK_DIR"
chown -R ga:ga "$TASK_DIR"

# Clean up any previous task artifacts to ensure a clean state
rm -f "$TASK_DIR/compliant_boston_building.ng3" 2>/dev/null || true
rm -f "$TASK_DIR/energy_results.png" 2>/dev/null || true

# Provide the starter sample file
SRC="/opt/energy3d_samples/building-shape.ng3"
DST="$TASK_DIR/building-shape.ng3"

if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

cp "$SRC" "$DST"
chown ga:ga "$DST"

# Record task start time for anti-gaming verification
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt

echo "Task start timestamp: $(cat /tmp/task_start_time.txt)"
echo "Starter file prepared at: $DST"

# Launch Energy3D using the helper function
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="