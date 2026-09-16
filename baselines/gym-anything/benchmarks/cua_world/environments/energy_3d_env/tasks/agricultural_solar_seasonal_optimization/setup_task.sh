#!/bin/bash
echo "=== Setting up agricultural_solar_seasonal_optimization task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task start time for anti-gaming (file creation must happen AFTER this)
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Ensure a clean slate: remove any previous artifacts
rm -f /home/ga/Documents/Energy3D/summer_irrigation_array.ng3
rm -f /home/ga/Documents/Energy3D/optimization_report.txt

# Launch Energy3D with an empty project (no file argument)
setup_energy3d_task ""

echo "=== Setup complete ==="