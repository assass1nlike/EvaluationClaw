#!/bin/bash
echo "=== Setting up residential_solar_payback_period_analysis task ==="

source /workspace/scripts/task_utils.sh

# Record task start time for anti-gaming verification
date +%s > /tmp/task_start_time.txt

# Ensure user directories exist
mkdir -p /home/ga/Documents/Energy3D
chown -R ga:ga /home/ga/Documents/Energy3D

# Clean up any potential previous task artifacts
rm -f /home/ga/Documents/Energy3D/sf_solar_home.ng3
rm -f /home/ga/Documents/Energy3D/payback_report.txt
rm -f /tmp/payback_report_result.txt
rm -f /tmp/task_result.json

# Launch a clean/blank Energy3D workspace
# Using the framework's task_utils.sh setup function with no file path
setup_energy3d_task ""

echo "=== Task setup complete ==="