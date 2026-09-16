#!/bin/bash
echo "=== Exporting weatherization result ==="

source /workspace/scripts/task_utils.sh || true

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TARGET="/home/ga/Documents/Energy3D/weatherized_home.ng3"

# Take final screenshot
take_screenshot /tmp/task_final.png

# Check if target file exists and was modified during task
if [ -f "$TARGET" ]; then
    OUTPUT_EXISTS="true"
    OUTPUT_SIZE=$(stat -c %s "$TARGET" 2>/dev/null || echo "0")
    OUTPUT_MTIME=$(stat -c %Y "$TARGET" 2>/dev/null || echo "0")
    
    if [ "$OUTPUT_MTIME" -ge "$TASK_START" ]; then
        FILE_CREATED_DURING_TASK="true"
    else
        FILE_CREATED_DURING_TASK="false"
    fi
else
    OUTPUT_EXISTS="false"
    OUTPUT_SIZE="0"
    FILE_CREATED_DURING_TASK="false"
fi

APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Create JSON result safely using temp file
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "output_exists": $OUTPUT_EXISTS,
    "output_size_bytes": $OUTPUT_SIZE,
    "file_created_during_task": $FILE_CREATED_DURING_TASK,
    "app_running": $APP_RUNNING,
    "task_start_time": $TASK_START,
    "export_timestamp": "$(date -Iseconds)"
}
EOF

# Move to final location avoiding permission issues
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="