#!/bin/bash
echo "=== Setting up datacenter_rooftop_solar_thermal_offset task ==="

source /workspace/scripts/task_utils.sh || { echo "WARNING: Failed to source task_utils"; }

# Define paths
TASK_NAME="datacenter_rooftop_solar_thermal_offset"
SRC="/opt/energy3d_samples/city-block.ng3"
DST="/home/ga/Documents/Energy3D/datacenter_start.ng3"
START_TS="/tmp/${TASK_NAME}_start_ts"

# Clean any previous artifacts
rm -f "$DST"
rm -f "/home/ga/Documents/Energy3D/datacenter_shaded.ng3"
rm -f "/home/ga/Documents/Energy3D/thermal_offset_results.csv"

# Verify source sample exists
if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

# Copy starter file to working directory
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record task start timestamp for anti-gaming checks
date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true
echo "Task start timestamp: $(cat $START_TS)"

# Launch Energy3D with the starter file
echo "Launching Energy3D..."
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="