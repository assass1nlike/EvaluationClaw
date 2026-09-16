#!/bin/bash
echo "=== Setting up commercial_solar_canopy_optimization task ==="

# Source environment utilities
source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="commercial_solar_canopy_optimization"
SRC="/opt/energy3d_samples/solar-canopy.ng3"
DST="/home/ga/Documents/Energy3D/solar-canopy.ng3"
TARGET="/home/ga/Documents/Energy3D/phoenix_canopy.ng3"
START_TS_FILE="/tmp/${TASK_NAME}_start_time"

# Ensure clean state (remove potential previous artifacts)
rm -f "$DST" "$TARGET" 2>/dev/null

if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

# Copy the starter file into the working directory
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record precise start time for anti-gaming verification
date +%s > "$START_TS_FILE"
echo "Task start timestamp: $(cat $START_TS_FILE)"

# Launch Energy3D utilizing the environment's utility script
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="