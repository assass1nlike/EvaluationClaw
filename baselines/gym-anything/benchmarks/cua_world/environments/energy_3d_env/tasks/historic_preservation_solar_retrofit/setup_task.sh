#!/bin/bash
echo "=== Setting up Historic Preservation Solar Retrofit Task ==="

source /workspace/scripts/task_utils.sh

# Record task start time (for anti-gaming verification)
START_TS=$(date +%s)
echo "$START_TS" > /tmp/task_start_time.txt

# Define paths
USER_DIR="/home/ga/Documents/Energy3D"
SRC_FILE="/opt/energy3d_samples/building-shape.ng3"
TARGET_FILE="$USER_DIR/building-shape.ng3"
OUTPUT_NG3="$USER_DIR/historic_retrofit.ng3"
OUTPUT_CSV="$USER_DIR/historic_solar_yield.csv"

# Clean up any pre-existing output files
rm -f "$OUTPUT_NG3" 2>/dev/null || true
rm -f "$OUTPUT_CSV" 2>/dev/null || true

# Prepare the starting file
mkdir -p "$USER_DIR"
if [ -f "$SRC_FILE" ]; then
    cp "$SRC_FILE" "$TARGET_FILE"
    chown ga:ga "$TARGET_FILE"
    echo "Starter file loaded: $TARGET_FILE"
else
    echo "WARNING: Source sample $SRC_FILE not found! Agent will start with blank scene."
fi

# Use the established utility to set up the Energy3D task
# This automatically handles process killing, launching, waiting, maximizing, and initial screenshot
setup_energy3d_task "$TARGET_FILE"

echo "=== Setup complete ==="