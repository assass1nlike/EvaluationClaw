#!/bin/bash
echo "=== Setting up high_latitude_telecom_solar_optimization task ==="

source /workspace/scripts/task_utils.sh

# Record task start time
date +%s > /tmp/task_start_time.txt

# Create working directory and copy the starter file
USER_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$USER_DIR"
chown ga:ga "$USER_DIR"

STARTER_FILE="$USER_DIR/solar-rack-array-row-spacing.ng3"
cp /opt/energy3d_samples/solar-rack-array-row-spacing.ng3 "$STARTER_FILE"
chown ga:ga "$STARTER_FILE"

# Clean up any potential artifacts from previous runs
rm -f "$USER_DIR/anchorage_telecom_site.ng3"
rm -f "$USER_DIR/anchorage_winter_yield.csv"

# Launch Energy3D with the starter file
echo "Launching Energy3D..."
setup_energy3d_task "$STARTER_FILE"

echo "=== Task setup complete ==="