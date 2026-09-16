#!/bin/bash
echo "=== Setting up bifacial_albedo_optimization task ==="

source /workspace/scripts/task_utils.sh

TASK_NAME="bifacial_albedo_optimization"
SRC="/opt/energy3d_samples/solar-rack-array.ng3"
DST="/home/ga/Documents/Energy3D/bifacial_baseline.ng3"

# Record task start time (for anti-gaming timestamp checks)
date +%s > /tmp/task_start_time.txt

# Remove any previous task artifacts to ensure clean slate
rm -f "/home/ga/Documents/Energy3D/bifacial_optimized.ng3" 2>/dev/null || true
rm -f "/home/ga/Documents/Energy3D/bifacial_yield.csv" 2>/dev/null || true

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Launch Energy3D maximizing windows and clearing dialogs
setup_energy3d_task "$DST"

echo "=== setup complete ==="