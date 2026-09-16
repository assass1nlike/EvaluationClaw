#!/bin/bash
echo "=== Setting up urban_zoning_right_to_light task ==="

# Source utility functions
source /workspace/scripts/task_utils.sh

# Define paths
SRC="/opt/energy3d_samples/city-block.ng3"
DST="/home/ga/Documents/Energy3D/city-block.ng3"
TARGET="/home/ga/Documents/Energy3D/chicago_zoning.ng3"

# Ensure clean state
rm -f "$TARGET" 2>/dev/null || true
rm -f /tmp/task_result.json 2>/dev/null || true

# Check if source sample exists
if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

# Copy the starter file into the user's workspace
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record task start time for anti-gaming verification
date +%s > /tmp/task_start_time.txt

# Launch Energy3D and open the starter file
# setup_energy3d_task takes care of launching, maximizing, dismissing dialogs, and initial screenshot
setup_energy3d_task "$DST"

echo "=== urban_zoning_right_to_light task setup complete ==="