#!/bin/bash
echo "=== Setting up off_grid_cold_storage_sizing task ==="

# Source the shared Energy3D GUI automation and setup tools
source /workspace/scripts/task_utils.sh || true

# Record task start time for anti-gaming verification
date +%s > /tmp/task_start_time.txt

SRC="/opt/energy3d_samples/building-orientation.ng3"
DST_DIR="/home/ga/Documents/Energy3D"
DST="$DST_DIR/building-orientation.ng3"
TARGET="/home/ga/Documents/Energy3D/cold_storage_solar.ng3"

# Ensure user directory exists
mkdir -p "$DST_DIR"
chown -R ga:ga "$DST_DIR"

# Remove any pre-existing target files to prevent stale state
rm -f "$TARGET"

# Copy the starter file into place
if [ -f "$SRC" ]; then
    cp "$SRC" "$DST"
    chown ga:ga "$DST"
else
    echo "WARNING: Source sample $SRC not found!"
fi

# Use the shared Energy3D task setup function:
# (Kills existing instances, launches with file, maximizes, and captures initial screenshot)
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="