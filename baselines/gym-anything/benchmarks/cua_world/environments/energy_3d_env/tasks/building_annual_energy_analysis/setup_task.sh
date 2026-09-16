#!/bin/bash
# Set up the building_annual_energy_analysis task: copy a real Energy3D
# building tutorial as the starter, then open Energy3D on it.
echo "=== Setting up building_annual_energy_analysis task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="building_annual_energy_analysis"
SRC="/opt/energy3d_samples/building-orientation.ng3"
DST="/home/ga/Documents/Energy3D/building_starter.ng3"
START_TS="/tmp/${TASK_NAME}_start_ts"

rm -f "$DST"

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

STARTER_SIZE=$(stat -c %s "$DST")
STARTER_MD5=$(md5sum "$DST" | awk '{print $1}')
echo "Starter file: $DST (size=$STARTER_SIZE, md5=$STARTER_MD5)"

date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true
echo "Task start timestamp: $(cat $START_TS)"

setup_energy3d_task "$DST"

echo "=== building_annual_energy_analysis task setup complete ==="
