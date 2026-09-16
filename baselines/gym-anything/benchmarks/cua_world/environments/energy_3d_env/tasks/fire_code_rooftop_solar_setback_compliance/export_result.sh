#!/bin/bash
echo "=== Exporting fire_code_rooftop_solar_setback_compliance result ==="

source /workspace/scripts/task_utils.sh

# Record task end time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

# Take final screenshot as primary VLM evidence
take_screenshot /tmp/task_final.png

NG3_FILE="/home/ga/Documents/Energy3D/fire_code_solar.ng3"
CSV_FILE="/home/ga/Documents/Energy3D/setback_compliant_yield.csv"

# Check the NG3 project file
NG3_EXISTS="false"
NG3_CREATED_DURING_TASK="false"
if [ -f "$NG3_FILE" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$NG3_FILE" 2>/dev/null || echo "0")
    if [ "$NG3_MTIME" -gt "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
fi

# Check the exported CSV file
CSV_EXISTS="false"
CSV_CREATED_DURING_TASK="false"
CSV_SIZE="0"
if [ -f "$CSV_FILE" ]; then
    CSV_EXISTS="true"
    CSV_MTIME=$(stat -c %Y "$CSV_FILE" 2>/dev/null || echo "0")
    CSV_SIZE=$(stat -c %s "$CSV_FILE" 2>/dev/null || echo "0")
    if [ "$CSV_MTIME" -gt "$TASK_START" ]; then
        CSV_CREATED_DURING_TASK="true"
    fi
fi

# Check if application was running
APP_RUNNING="false"
if pgrep -f "Energy3D" > /dev/null; then
    APP_RUNNING="true"
fi

# Export to JSON format via temp file to avoid permission issues
TEMP_JSON=$(mktemp /tmp/task_result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "app_was_running": $APP_RUNNING,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "csv_exists": $CSV_EXISTS,
    "csv_created_during_task": $CSV_CREATED_DURING_TASK,
    "csv_size_bytes": $CSV_SIZE,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move and set permissions
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON written:"
cat /tmp/task_result.json
echo "=== Export complete ==="