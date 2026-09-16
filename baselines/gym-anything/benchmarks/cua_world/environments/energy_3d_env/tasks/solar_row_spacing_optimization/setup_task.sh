#!/bin/bash
echo "=== Setting up solar_row_spacing_optimization task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task start time (for anti-gaming verification)
date +%s > /tmp/task_start_ts
chown ga:ga /tmp/task_start_ts 2>/dev/null || true

# Define paths
USER_DIR="/home/ga/Documents/Energy3D"
SRC_FILE="/opt/energy3d_samples/solar-rack-array-row-spacing.ng3"
START_FILE="$USER_DIR/solar-rack-array-row-spacing.ng3"

# Clean up any potential artifacts from previous runs
rm -f "$USER_DIR/winter_yield_optimized.csv"
rm -f "$USER_DIR/optimized_array.ng3"
rm -f "/tmp/task_result.json"

# Ensure data directory exists and copy starter file
mkdir -p "$USER_DIR"
if [ -f "$SRC_FILE" ]; then
    cp "$SRC_FILE" "$START_FILE"
    chown ga:ga "$START_FILE" 2>/dev/null || true
    echo "Starter file prepared at: $START_FILE"
else
    echo "ERROR: Missing starter file: $SRC_FILE"
    exit 1
fi

# Launch Energy3D
# We launch without auto-opening the file so the agent must do "File -> Open" 
# or we can auto-open it. Task description says "Energy3D is open. The file ... is available".
# Let's start the app clean.
kill_energy3d

echo "Launching Energy3D..."
su - ga -c "setsid /opt/energy3d/energy3d.sh > /tmp/energy3d_task.log 2>&1 &"

# Wait for application to fully render
sleep 10

# Dismiss startup dialogs
dismiss_dialogs 4

# Maximize window
maximize_energy3d
sleep 2

# Take initial screenshot for evidence
take_screenshot /tmp/task_initial_state.png

echo "=== Task setup complete ==="