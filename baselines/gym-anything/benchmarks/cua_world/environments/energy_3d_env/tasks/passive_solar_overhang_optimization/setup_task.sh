#!/bin/bash
echo "=== Setting up passive_solar_overhang_optimization task ==="

source /workspace/scripts/task_utils.sh || { echo "WARNING: Failed to source task_utils"; }

TASK_NAME="passive_solar_overhang_optimization"
SRC="/opt/energy3d_samples/building-passive-heating.ng3"
DST="/home/ga/Documents/Energy3D/building-passive-heating.ng3"
START_TS="/tmp/${TASK_NAME}_start_ts"

# Ensure the documents directory exists
mkdir -p "$(dirname "$DST")"

# Clean any existing artifacts from previous runs
rm -f "$DST"
rm -f "/home/ga/Documents/Energy3D/phoenix_passive.ng3"

# Copy the starter file
if [ -f "$SRC" ]; then
    cp "$SRC" "$DST"
    chown ga:ga "$DST" 2>/dev/null || true
    echo "Starter file prepared at: $DST"
else
    echo "ERROR: Source sample not found at $SRC"
    # Create an empty file just so it doesn't hard-crash the script, though task will be broken
    touch "$DST"
fi

# Record the start time for anti-gaming verification
date +%s > "$START_TS"
chown ga:ga "$START_TS" 2>/dev/null || true
echo "Task start timestamp: $(cat $START_TS)"

# Launch Energy3D without auto-loading the file, forcing the agent to open it
# OR we can auto-load it to save repetitive UI steps. The prompt says "Open the project file..."
# Let's start the app empty so the agent practices file navigation.
if type setup_energy3d_task &>/dev/null; then
    setup_energy3d_task ""
else
    # Fallback if task_utils isn't loaded properly
    su - ga -c "DISPLAY=:1 /opt/energy3d/energy3d.sh &"
    sleep 8
    DISPLAY=:1 wmctrl -r "Energy3D" -b add,maximized_vert,maximized_horz 2>/dev/null || true
    DISPLAY=:1 scrot /tmp/task_start_screenshot.png 2>/dev/null || true
fi

echo "=== passive_solar_overhang_optimization task setup complete ==="