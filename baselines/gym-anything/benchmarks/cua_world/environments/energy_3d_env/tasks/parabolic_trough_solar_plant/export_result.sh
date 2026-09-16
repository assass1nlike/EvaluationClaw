#!/bin/bash
echo "=== Exporting parabolic_trough_solar_plant result ==="

source /workspace/scripts/task_utils.sh

# Take final screenshot before checking files
take_screenshot /tmp/task_final.png

TARGET_FILE="/home/ga/Documents/Energy3D/trough_plant.ng3"
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

FILE_EXISTS="false"
FILE_CREATED_DURING_TASK="false"
FILE_SIZE="0"
HAS_PHOENIX_STRING="false"
HAS_TROUGH_STRING="false"

if [ -f "$TARGET_FILE" ]; then
    FILE_EXISTS="true"
    FILE_SIZE=$(stat -c %s "$TARGET_FILE" 2>/dev/null || echo "0")
    FILE_MTIME=$(stat -c %Y "$TARGET_FILE" 2>/dev/null || echo "0")
    
    if [ "$FILE_MTIME" -gt "$TASK_START" ]; then
        FILE_CREATED_DURING_TASK="true"
    fi
    
    # Energy3D .ng3 files are Java serialized binaries. 
    # We can use strings to extract basic heuristic properties.
    if strings "$TARGET_FILE" | grep -qi "Phoenix"; then
        HAS_PHOENIX_STRING="true"
    fi
    if strings "$TARGET_FILE" | grep -qi "ParabolicTrough"; then
        HAS_TROUGH_STRING="true"
    fi
fi

# Check if application is running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Write results to JSON safely
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start_time": $TASK_START,
    "file_exists": $FILE_EXISTS,
    "file_created_during_task": $FILE_CREATED_DURING_TASK,
    "file_size_bytes": $FILE_SIZE,
    "has_phoenix_string": $HAS_PHOENIX_STRING,
    "has_trough_string": $HAS_TROUGH_STRING,
    "app_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move to final location safely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON saved to /tmp/task_result.json"
cat /tmp/task_result.json

# Gracefully close Energy3D
kill_energy3d

echo "=== Export complete ==="