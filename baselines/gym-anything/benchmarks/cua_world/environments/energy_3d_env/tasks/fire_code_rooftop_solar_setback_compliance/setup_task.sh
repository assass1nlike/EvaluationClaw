#!/bin/bash
echo "=== Setting up fire_code_rooftop_solar_setback_compliance task ==="

source /workspace/scripts/task_utils.sh

# Record task start time for anti-gaming verification
date +%s > /tmp/task_start_time.txt

# Ensure target directories exist
mkdir -p /home/ga/Documents/Energy3D

# Clean up any previous artifacts from previous runs
rm -f /home/ga/Documents/Energy3D/fire_code_solar.ng3
rm -f /home/ga/Documents/Energy3D/setback_compliant_yield.csv

# Define source and destination for the starter project
SRC_FILE="/opt/energy3d_samples/building-roof-insulation.ng3"
STARTER_FILE="/home/ga/Documents/Energy3D/building-roof-insulation.ng3"

if [ ! -f "$SRC_FILE" ]; then
    echo "ERROR: Source sample not found at $SRC_FILE"
    exit 1
fi

# Copy starter project to user's documents
cp "$SRC_FILE" "$STARTER_FILE"
chown ga:ga "$STARTER_FILE"

# Launch Energy3D with the starter file
echo "Launching Energy3D..."
setup_energy3d_task "$STARTER_FILE"

# Give UI time to stabilize
sleep 2

# Verify task started successfully
if pgrep -f "Energy3D" > /dev/null; then
    echo "Energy3D is running."
else
    echo "WARNING: Energy3D failed to start."
fi

# Take initial screenshot to capture the initial state (house with no panels)
take_screenshot /tmp/task_initial_state.png

echo "=== Task setup complete ==="