#!/bin/bash
set -e
echo "=== Setting up urban_rooftop_solar_assessment ==="

# Source utility functions
source /workspace/scripts/task_utils.sh

# Record task start time for anti-gaming (file modification checks)
date +%s > /tmp/task_start_time.txt

# Set up working directory and files
DOC_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$DOC_DIR"

# Ensure clean state (remove potential previous artifacts)
rm -f "$DOC_DIR/city_block_upgraded.ng3"
rm -f "$DOC_DIR/tallest_building_yield.csv"

# Copy the real sample dataset to the working directory
SRC_FILE="/opt/energy3d_samples/city-block.ng3"
DST_FILE="$DOC_DIR/city-block.ng3"

if [ ! -f "$SRC_FILE" ]; then
    echo "ERROR: Source sample not found: $SRC_FILE"
    exit 1
fi

cp "$SRC_FILE" "$DST_FILE"
chown -R ga:ga "$DOC_DIR"

# Launch Energy3D and load the starting project
setup_energy3d_task "$DST_FILE"

echo "=== Task setup complete ==="