#!/bin/bash
set -e
echo "=== Setting up southern_hemisphere_mine_solar_orientation task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task start time (for anti-gaming verification)
date +%s > /tmp/task_start_time.txt

# Use a built-in standard solar array sample as the "draft"
SRC="/opt/energy3d_samples/solar-rack-array.ng3"
DST_DIR="/home/ga/Documents/Energy3D"
DST="$DST_DIR/mine_site_draft.ng3"
CORRECTED_FILE="$DST_DIR/mine_site_corrected.ng3"

# Clean any existing artifacts from previous runs
rm -f "$DST"
rm -f "$CORRECTED_FILE"
mkdir -p "$DST_DIR"

if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found at $SRC"
    exit 1
fi

# Copy the file to the target location
cp "$SRC" "$DST"
chown -R ga:ga "$DST_DIR"

# Launch Energy3D with the starting file
setup_energy3d_task "$DST"

echo "=== Setup complete ==="