#!/bin/bash
echo "=== Setting up remote_clinic_netzero_design task ==="

# Source utilities
source /workspace/scripts/task_utils.sh

# Record task start time for anti-gaming timestamp checks
date +%s > /tmp/task_start_time.txt

# Define paths
SRC="/opt/energy3d_samples/building-shape.ng3"
DST="/home/ga/Documents/Energy3D/building-shape.ng3"

# Ensure clean state
rm -f "/home/ga/Documents/Energy3D/phoenix_clinic.ng3" 2>/dev/null || true
rm -f "/home/ga/Documents/Energy3D/phoenix_clinic_energy.csv" 2>/dev/null || true

# Copy starting file
if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Launch Energy3D with the starter file using the utility function
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="