#!/bin/bash
echo "=== Setting up industrial_sawtooth_solar_design task ==="

# Source shared utilities for Energy3D
source /workspace/scripts/task_utils.sh

# Record task start time for anti-gaming timestamp checks
date +%s > /tmp/task_start_time.txt

# Create working directory
USER_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$USER_DIR"

# Provide a realistic base building model from the official tutorial dataset
# We use building-shape.ng3 as a proxy for the basic flat-roof factory base
SRC_FILE="/opt/energy3d_samples/building-shape.ng3"
BASE_FILE="$USER_DIR/factory_base.ng3"

# Clean up any potential artifacts from previous runs
rm -f "$BASE_FILE"
rm -f "$USER_DIR/factory_sawtooth_solar.ng3"
rm -f "$USER_DIR/factory_annual_energy.csv"

# Copy base file
if [ -f "$SRC_FILE" ]; then
    cp "$SRC_FILE" "$BASE_FILE"
    echo "Copied base factory project."
else
    echo "ERROR: Base sample not found at $SRC_FILE!"
    exit 1
fi

# Set proper ownership
chown -R ga:ga "$USER_DIR"

# Setup Energy3D via the environment's utility function
# This launches the app, maximizes the window, and takes an initial screenshot
setup_energy3d_task "$BASE_FILE"

echo "=== Task setup complete ==="