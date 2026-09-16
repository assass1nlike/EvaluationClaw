#!/bin/bash
echo "=== Setting up commercial_skylight_energy_tradeoff task ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task start time
date +%s > /tmp/task_start_time.txt

# Define paths
USER_DIR="/home/ga/Documents/Energy3D"
SRC="/opt/energy3d_samples/building-roof-insulation.ng3"
DST="$USER_DIR/building-roof-insulation.ng3"
REPORT_PATH="$USER_DIR/skylight_tradeoff_report.txt"
PROJECT_PATH="$USER_DIR/building_with_skylights.ng3"

# Clean any existing artifacts from previous runs
rm -f "$REPORT_PATH"
rm -f "$PROJECT_PATH"

# Ensure user directory exists and has the starter file
mkdir -p "$USER_DIR"
if [ ! -f "$SRC" ]; then
    echo "ERROR: source sample not found: $SRC"
    exit 1
fi
cp "$SRC" "$DST"
chown -R ga:ga "$USER_DIR"

# Launch Energy3D with the starter file
echo "Launching Energy3D..."
setup_energy3d_task "$DST"

# Save initial state metadata
cat > /tmp/initial_state.json << EOF
{
    "task_start_time": $(cat /tmp/task_start_time.txt),
    "starter_file_exists": true
}
EOF

echo "=== Task setup complete ==="