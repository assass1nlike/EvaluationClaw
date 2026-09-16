#!/bin/bash
echo "=== Exporting task results ==="

source /workspace/scripts/task_utils.sh

# Take final screenshot for verification
take_screenshot /tmp/task_final.png

# Retrieve task start time
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
USER_DIR="/home/ga/Documents/Energy3D"

PROJ_PATH="$USER_DIR/agrivoltaics_array.ng3"
CSV_PATH="$USER_DIR/agrivoltaics_yield.csv"

# 1. Check if the modified project file was saved
PROJ_EXISTS="false"
PROJ_SIZE="0"
PROJ_NEW="false"
if [ -f "$PROJ_PATH" ]; then
    PROJ_EXISTS="true"
    PROJ_SIZE=$(stat -c %s "$PROJ_PATH")
    PROJ_MTIME=$(stat -c %Y "$PROJ_PATH")
    if [ "$PROJ_MTIME" -ge "$TASK_START" ]; then
        PROJ_NEW="true"
    fi
fi

# 2. Check if the yield CSV was exported
CSV_EXISTS="false"
CSV_SIZE="0"
CSV_NEW="false"
CSV_LINES="0"
if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c %s "$CSV_PATH")
    CSV_MTIME=$(stat -c %Y "$CSV_PATH")
    CSV_LINES=$(wc -l < "$CSV_PATH" 2>/dev/null || echo "0")
    if [ "$CSV_MTIME" -ge "$TASK_START" ]; then
        CSV_NEW="true"
    fi
fi

# 3. Check if Energy3D is still running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Generate JSON result file
TEMP_JSON=$(mktemp /tmp/task_result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "proj_exists": $PROJ_EXISTS,
    "proj_size": $PROJ_SIZE,
    "proj_new": $PROJ_NEW,
    "csv_exists": $CSV_EXISTS,
    "csv_size": $CSV_SIZE,
    "csv_new": $CSV_NEW,
    "csv_lines": $CSV_LINES,
    "app_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move to final location safely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="