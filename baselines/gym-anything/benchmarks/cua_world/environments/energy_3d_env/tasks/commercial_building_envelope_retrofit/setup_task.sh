#!/bin/bash
echo "=== Setting up commercial_building_envelope_retrofit task ==="

# Source Energy3D utilities
source /workspace/scripts/task_utils.sh

# Record task start time for anti-gaming checks
date +%s > /tmp/task_start_time.txt

# Prepare baseline file from real Energy3D tutorial sample
USER_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$USER_DIR"
BASELINE_PATH="$USER_DIR/office_baseline.ng3"

# We use the passive heating tutorial model as a sturdy baseline building to retrofit
cp /opt/energy3d_samples/building-passive-heating.ng3 "$BASELINE_PATH"
chown -R ga:ga "$USER_DIR"

# Ensure clean state (remove any artifacts from previous runs)
rm -f "$USER_DIR/office_upgraded.ng3"
rm -f "$USER_DIR/cooling_results.txt"

echo "Baseline file prepared at: $BASELINE_PATH"

# Launch Energy3D and open the baseline file
echo "Launching Energy3D..."
setup_energy3d_task "$BASELINE_PATH"

# Give it an extra moment to ensure the UI has settled
sleep 2

# Take initial verification screenshot
take_screenshot /tmp/task_initial.png

echo "=== Setup complete ==="