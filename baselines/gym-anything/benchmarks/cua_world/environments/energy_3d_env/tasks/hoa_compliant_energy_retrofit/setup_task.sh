#!/bin/bash
echo "=== Setting up hoa_compliant_energy_retrofit task ==="

# Source utilities
source /workspace/scripts/task_utils.sh

# Define paths
SRC="/opt/energy3d_samples/building-passive-heating.ng3"
DST="/home/ga/Documents/Energy3D/building-passive-heating.ng3"
OUT="/home/ga/Documents/Energy3D/hoa_compliant_retrofit.ng3"

# Clean up any previous task artifacts
rm -f "$OUT" 2>/dev/null || true

# Check if source sample exists
if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

# Copy sample to user directory
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record task start time for anti-gaming (file modification check)
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Start Energy3D using the provided environment utility
# This utility handles launching, maximizing, dismissing dialogs, and initial screenshots
setup_energy3d_task "$DST"

echo "=== Setup complete ==="