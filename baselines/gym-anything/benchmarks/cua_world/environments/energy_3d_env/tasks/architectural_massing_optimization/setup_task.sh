#!/bin/bash
echo "=== Setting up architectural massing optimization task ==="

source /workspace/scripts/task_utils.sh

# Record task start time for anti-gaming timestamp checks
date +%s > /tmp/task_start_time

# Define file paths
SRC="/opt/energy3d_samples/building-shape.ng3"
DST="/home/ga/Documents/Energy3D/building-shape.ng3"

OUTPUT_CSV="/home/ga/Documents/Energy3D/anchorage_energy.csv"
OUTPUT_TXT="/home/ga/Documents/Energy3D/best_massing.txt"
OUTPUT_NG3="/home/ga/Documents/Energy3D/anchorage-optimized.ng3"

# Clean up any pre-existing output files from previous runs
rm -f "$OUTPUT_CSV" "$OUTPUT_TXT" "$OUTPUT_NG3" 2>/dev/null

# Ensure the source file exists
if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found at $SRC"
    exit 1
fi

# Copy the sample file to the working directory
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Start Energy3D with the target file loaded, wait for render, and maximize
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="