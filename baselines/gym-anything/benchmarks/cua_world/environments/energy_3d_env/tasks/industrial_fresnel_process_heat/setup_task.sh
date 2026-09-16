#!/bin/bash
echo "=== Setting up industrial_fresnel_process_heat task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Ensure working directory exists
mkdir -p /home/ga/Documents/Energy3D
chown -R ga:ga /home/ga/Documents/Energy3D

# Clear any existing target output files to ensure clean state
rm -f /home/ga/Documents/Energy3D/fresnel_plant.ng3 2>/dev/null
rm -f /home/ga/Documents/Energy3D/fresnel_output.csv 2>/dev/null

# Record task start timestamp for anti-gaming verification
START_TS="/tmp/industrial_fresnel_process_heat_start_ts"
date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true

# Launch Energy3D with a fresh, blank scene (no starter file)
setup_energy3d_task ""

echo "=== Setup complete ==="