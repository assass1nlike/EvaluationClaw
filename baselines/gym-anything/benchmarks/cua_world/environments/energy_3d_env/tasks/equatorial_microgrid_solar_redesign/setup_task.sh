#!/bin/bash
echo "=== Setting up equatorial_microgrid_solar_redesign task ==="

source /workspace/scripts/task_utils.sh

TASK_NAME="equatorial_microgrid_solar_redesign"
SRC="/opt/energy3d_samples/solar-panel-tilt-angle.ng3"
DST="/home/ga/Documents/Energy3D/solar-panel-tilt-angle.ng3"
OUT_CSV="/home/ga/Documents/Energy3D/nairobi_yield.csv"
OUT_NG3="/home/ga/Documents/Energy3D/nairobi_microgrid.ng3"

# Clean up any artifacts
rm -f "$OUT_CSV" "$OUT_NG3" "$DST"

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record task start time
date +%s > /tmp/task_start_time

# Launch Energy3D with the starter file
setup_energy3d_task "$DST"

echo "=== Task setup complete ==="