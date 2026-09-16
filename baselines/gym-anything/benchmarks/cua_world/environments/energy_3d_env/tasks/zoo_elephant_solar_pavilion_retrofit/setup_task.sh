#!/bin/bash
echo "=== Setting up Zoo Elephant Solar Pavilion Retrofit task ==="

# Source environment utilities
source /workspace/scripts/task_utils.sh

# Define paths
USER_DOCS="/home/ga/Documents/Energy3D"
START_FILE_SRC="/opt/energy3d_samples/solar-canopy.ng3"
START_FILE_DST="$USER_DOCS/solar-canopy.ng3"

# Clean any previous artifacts
mkdir -p "$USER_DOCS"
rm -f "$USER_DOCS/phoenix_elephant_pavilion.ng3"
rm -f "$USER_DOCS/elephant_pavilion_yield.csv"

# Verify source sample exists
if [ ! -f "$START_FILE_SRC" ]; then
    echo "ERROR: Source sample not found: $START_FILE_SRC"
    exit 1
fi

# Copy the file to the user's document folder
cp "$START_FILE_SRC" "$START_FILE_DST"
chown -R ga:ga "$USER_DOCS"

# Record task start timestamp for anti-gaming (file creation timestamp verification)
date +%s > /tmp/task_start_time.txt
echo "Task start timestamp: $(cat /tmp/task_start_time.txt)"

# Launch Energy3D with the starter file
setup_energy3d_task "$START_FILE_DST"

echo "=== Task setup complete ==="