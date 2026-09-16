#!/bin/bash
echo "=== Exporting passive_solar_overhang_optimization result ==="

# Fallback screenshot command if task_utils isn't available
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || DISPLAY=:1 import -window root /tmp/task_final.png 2>/dev/null || true

TASK_NAME="passive_solar_overhang_optimization"
START_TS=$(cat "/tmp/${TASK_NAME}_start_ts" 2>/dev/null || echo "0")
OUT_FILE="/home/ga/Documents/Energy3D/phoenix_passive.ng3"

FILE_EXISTS="false"
FILE_SIZE=0
FILE_CREATED_DURING_TASK="false"

if [ -f "$OUT_FILE" ]; then
    FILE_EXISTS="true"
    FILE_SIZE=$(stat -c %s "$OUT_FILE" 2>/dev/null || echo "0")
    FILE_MTIME=$(stat -c %Y "$OUT_FILE" 2>/dev/null || echo "0")
    
    if [ "$FILE_MTIME" -gt "$START_TS" ]; then
        FILE_CREATED_DURING_TASK="true"
    fi
fi

APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start_time": $START_TS,
    "output_exists": $FILE_EXISTS,
    "output_size_bytes": $FILE_SIZE,
    "file_created_during_task": $FILE_CREATED_DURING_TASK,
    "app_was_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png",
    "output_path": "$OUT_FILE"
}
EOF

# Move temp file to final location safely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="