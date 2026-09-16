#!/bin/bash
echo "=== Setting up hvac_thermostat_setback_savings task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task start time for anti-gaming
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Prepare the data
SRC="/opt/energy3d_samples/building-passive-heating.ng3"
DST="/home/ga/Documents/Energy3D/building-passive-heating.ng3"

if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

# Ensure pristine initial state
rm -f "/home/ga/Documents/Energy3D/eco_building.ng3" 2>/dev/null || true
rm -f "/home/ga/Documents/Energy3D/thermostat_savings_report.txt" 2>/dev/null || true

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Launch Energy3D with the starter file
echo "Launching Energy3D..."
setup_energy3d_task "$DST"

echo "=== Setup complete ==="