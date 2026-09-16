#!/bin/bash
echo "=== Setting up residential_weatherization_energy_audit task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task start time (for anti-gaming timestamp checks)
date +%s > /tmp/task_start_time.txt

SRC="/opt/energy3d_samples/building-passive-heating.ng3"
DST="/home/ga/Documents/Energy3D/building-passive-heating.ng3"
TARGET="/home/ga/Documents/Energy3D/weatherized_home.ng3"

# Clean up any existing state/artifacts
rm -f "$DST" "$TARGET" 2>/dev/null

if [ ! -f "$SRC" ]; then
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

# Copy the sample to the working directory
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

echo "Starter file prepared at: $DST"

# Launch Energy3D with the starter file
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="