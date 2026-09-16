#!/bin/bash
echo "=== Setting up railway_corridor_vertical_solar_fence task ==="

# Source environment utilities
source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Establish paths
USER_DIR="/home/ga/Documents/Energy3D"
SRC="/opt/energy3d_samples/solar-rack-array-row-spacing.ng3"
DST="$USER_DIR/solar-rack-array-row-spacing.ng3"

mkdir -p "$USER_DIR"

# Clean any existing artifacts from previous runs
rm -f "$DST"
rm -f "$USER_DIR/vertical_solar_fence.ng3"
rm -f "$USER_DIR/fence_yield.txt"

# Ensure source file exists
if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

# Copy official sample data to serve as the starter file
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record task start timestamp for anti-gaming verification
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Launch Energy3D natively and safely via utility function
setup_energy3d_task "$DST"

echo "=== Setup complete ==="