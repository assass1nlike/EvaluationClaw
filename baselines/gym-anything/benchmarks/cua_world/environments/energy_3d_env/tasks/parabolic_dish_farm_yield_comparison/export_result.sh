#!/bin/bash
echo "=== Exporting task results ==="

source /workspace/scripts/task_utils.sh

# Take final screenshot before any windows are closed
take_screenshot /tmp/task_final.png

# Capture timestamps
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TASK_END=$(date +%s)

# File paths
FINAL_NG3="/home/ga/Documents/Energy3D/dish_farm_final.ng3"
FINAL_TXT="/home/ga/Documents/Energy3D/yield_comparison.txt"

# Check if .ng3 file was created/modified during task
NG3_EXISTS="false"
NG3_CREATED_DURING_TASK="false"
if [ -f "$FINAL_NG3" ]; then
    NG3_EXISTS="true"
    MTIME=$(stat -c %Y "$FINAL_NG3" 2>/dev/null || echo "0")
    if [ "$MTIME" -gt "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
fi

# Check if text report was created/modified during task
TXT_EXISTS="false"
TXT_CREATED_DURING_TASK="false"
if [ -f "$FINAL_TXT" ]; then
    TXT_EXISTS="true"
    MTIME=$(stat -c %Y "$FINAL_TXT" 2>/dev/null || echo "0")
    if [ "$MTIME" -gt "$TASK_START" ]; then
        TXT_CREATED_DURING_TASK="true"
    fi
fi

# Check if application is running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Export metrics securely using a temporary JSON payload
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "app_was_running": $APP_RUNNING,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "txt_exists": $TXT_EXISTS,
    "txt_created_during_task": $TXT_CREATED_DURING_TASK
}
EOF

# Move payload to standardized location
rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Result exported to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="