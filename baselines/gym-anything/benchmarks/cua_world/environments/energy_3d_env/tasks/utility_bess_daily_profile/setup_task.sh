#!/bin/bash
echo "=== Setting up utility_bess_daily_profile task ==="

# Source utilities
source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task start time for anti-gaming checks
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Prepare the starting environment
mkdir -p /home/ga/Documents/Energy3D
SRC="/opt/energy3d_samples/solar-rack-array.ng3"
DST="/home/ga/Documents/Energy3D/solar_array_starter.ng3"

# Ensure clean slate
rm -f "$DST"
rm -f /home/ga/Documents/Energy3D/phoenix_bess_array.ng3
rm -f /home/ga/Documents/Energy3D/solstice_hourly_profile.csv
rm -f /home/ga/Documents/Energy3D/peak_charge_hour.txt

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

# Copy the real starting asset
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

echo "Task start timestamp: $(cat /tmp/task_start_time.txt)"

# Launch Energy3D with the starter file and take an initial screenshot
setup_energy3d_task "$DST"

echo "=== utility_bess_daily_profile task setup complete ==="