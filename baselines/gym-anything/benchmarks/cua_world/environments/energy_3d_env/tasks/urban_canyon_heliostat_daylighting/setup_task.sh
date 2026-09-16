#!/bin/bash
echo "=== Setting up urban_canyon_heliostat_daylighting task ==="

source /workspace/scripts/task_utils.sh || { echo "WARNING: Failed to source task_utils.sh"; }

# Define paths
USER_DIR="/home/ga/Documents/Energy3D"
SRC="/opt/energy3d_samples/city-block.ng3"
DST="$USER_DIR/city-block.ng3"
TARGET_NG3="$USER_DIR/city-block-heliostat.ng3"
TARGET_PNG="$USER_DIR/heliostat_rays.png"

# Ensure directory exists
mkdir -p "$USER_DIR"

# Clean up any artifacts from previous runs
rm -f "$TARGET_NG3" 2>/dev/null || true
rm -f "$TARGET_PNG" 2>/dev/null || true

# Copy starter project
if [ -f "$SRC" ]; then
    cp "$SRC" "$DST"
    chown ga:ga "$DST"
else
    echo "ERROR: Source sample not found: $SRC"
    exit 1
fi

# Record start time for anti-gaming (file modification check)
date +%s > /tmp/task_start_time.txt
chown ga:ga /tmp/task_start_time.txt 2>/dev/null || true

# Launch Energy3D with the starter file
if type setup_energy3d_task >/dev/null 2>&1; then
    setup_energy3d_task "$DST"
else
    # Fallback if utility function missing
    su - ga -c "DISPLAY=:1 /opt/energy3d/energy3d.sh \"$DST\" &"
    sleep 15
    DISPLAY=:1 wmctrl -r "Energy3D" -b add,maximized_vert,maximized_horz 2>/dev/null || true
    DISPLAY=:1 scrot /tmp/task_start_screenshot.png 2>/dev/null || true
fi

echo "=== Setup complete ==="