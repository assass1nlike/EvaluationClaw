#!/bin/bash
# Set up the solar_panel_array_design task: copy a real Energy3D sample
# project into the user's working directory and open Energy3D on it.
echo "=== Setting up solar_panel_array_design task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="solar_panel_array_design"
SRC="/opt/energy3d_samples/solar-rack-array.ng3"
DST="/home/ga/Documents/Energy3D/solar_array_starter.ng3"
START_TS="/tmp/${TASK_NAME}_start_ts"

# Clean stale artifacts so the verifier can detect new modifications.
rm -f "$DST"

if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
chown ga:ga "$DST" 2>/dev/null || true

# Record the size and md5 of the starter so a verifier can confirm modification.
STARTER_SIZE=$(stat -c %s "$DST")
STARTER_MD5=$(md5sum "$DST" | awk '{print $1}')
echo "Starter file: $DST (size=$STARTER_SIZE, md5=$STARTER_MD5)"

date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true
echo "Task start timestamp: $(cat $START_TS)"

# Launch Energy3D with the starter file.
setup_energy3d_task "$DST"

echo "=== solar_panel_array_design task setup complete ==="
