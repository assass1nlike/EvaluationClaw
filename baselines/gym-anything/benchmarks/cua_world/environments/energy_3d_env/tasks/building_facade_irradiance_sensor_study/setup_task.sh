#!/bin/bash
echo "=== Setting up building_facade_irradiance_sensor_study task ==="

source /workspace/scripts/task_utils.sh

# Record start time for anti-gaming (comparing against output mtimes)
date +%s > /tmp/task_start_time.txt

# Define paths
SRC="/opt/energy3d_samples/building-shape.ng3"
USER_DIR="/home/ga/Documents/Energy3D"
DST="$USER_DIR/building_shape.ng3"
TARGET_MODEL="$USER_DIR/facade_sensors.ng3"
TARGET_GRAPH="$USER_DIR/sensor_graph.png"

# Clean up any previous artifacts
rm -f "$TARGET_MODEL"
rm -f "$TARGET_GRAPH"
mkdir -p "$USER_DIR"

if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

# Copy starter file
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

echo "Starter file ready: $DST"

# Use the environment's provided task setup function (handles killing existing, launching, waiting, maximizing)
setup_energy3d_task "$DST"

# Take initial state screenshot for trajectory evidence
take_screenshot /tmp/task_initial.png

echo "=== Setup complete ==="