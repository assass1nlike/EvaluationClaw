#!/bin/bash
echo "=== Setting up urban_school_courtyard_addition task ==="

source /workspace/scripts/task_utils.sh

# Record task start time (for anti-gaming verification)
date +%s > /tmp/task_start_time.txt

SRC="/opt/energy3d_samples/city-block.ng3"
DST="/home/ga/Documents/Energy3D/city-block.ng3"

# Remove any previous task artifacts
rm -f /home/ga/Documents/Energy3D/city_school_addition.ng3 2>/dev/null || true

# Check if source sample exists
if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

# Copy sample to user documents
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Launch Energy3D with the starter file and take initial screenshot
setup_energy3d_task "$DST"

echo "=== urban_school_courtyard_addition task setup complete ==="