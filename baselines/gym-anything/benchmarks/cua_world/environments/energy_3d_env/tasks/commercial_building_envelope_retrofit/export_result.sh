#!/bin/bash
echo "=== Exporting commercial_building_envelope_retrofit result ==="

source /workspace/scripts/task_utils.sh

# Take final state screenshot
take_screenshot /tmp/task_final.png

# Paths
UPGRADED_FILE="/home/ga/Documents/Energy3D/office_upgraded.ng3"
RESULTS_FILE="/home/ga/Documents/Energy3D/cooling_results.txt"
START_TIME=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

# Check upgraded NG3 file
FILE_EXISTS="false"
FILE_MODIFIED_DURING_TASK="false"
FILE_SIZE="0"

if [ -f "$UPGRADED_FILE" ]; then
    FILE_EXISTS="true"
    FILE_SIZE=$(stat -c %s "$UPGRADED_FILE" 2>/dev/null || echo "0")
    FILE_MTIME=$(stat -c %Y "$UPGRADED_FILE" 2>/dev/null || echo "0")
    
    if [ "$FILE_MTIME" -gt "$START_TIME" ]; then
        FILE_MODIFIED_DURING_TASK="true"
    fi
fi

# Check text file results
RESULTS_EXISTS="false"
RESULTS_MTIME="0"

if [ -f "$RESULTS_FILE" ]; then
    RESULTS_EXISTS="true"
    RESULTS_MTIME=$(stat -c %Y "$RESULTS_FILE" 2>/dev/null || echo "0")
fi

# Determine if Energy3D is still running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Write results to JSON
TEMP_JSON=$(mktemp /tmp/retrofit_result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start_time": $START_TIME,
    "app_running": $APP_RUNNING,
    "upgraded_file_exists": $FILE_EXISTS,
    "upgraded_file_modified_during_task": $FILE_MODIFIED_DURING_TASK,
    "upgraded_file_size": $FILE_SIZE,
    "results_file_exists": $RESULTS_EXISTS,
    "results_file_mtime": $RESULTS_MTIME,
    "timestamp": "$(date -Iseconds)"
}
EOF

# Move securely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Export details:"
cat /tmp/task_result.json
echo "=== Export complete ==="