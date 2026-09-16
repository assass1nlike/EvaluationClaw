#!/bin/bash
echo "=== Exporting floatovoltaics_yield_simulation task result ==="

source /workspace/scripts/task_utils.sh

# Record task end time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

# Take final screenshot as visual evidence
take_screenshot /tmp/task_final.png

# Check for the expected CSV output file
CSV_PATH="/home/ga/Documents/Energy3D/fpv_yield.csv"
CSV_EXISTS="false"
CSV_CREATED_DURING_TASK="false"
CSV_SIZE="0"
CSV_LINES="0"

if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c %s "$CSV_PATH" 2>/dev/null || echo "0")
    CSV_MTIME=$(stat -c %Y "$CSV_PATH" 2>/dev/null || echo "0")
    CSV_LINES=$(wc -l < "$CSV_PATH" 2>/dev/null || echo "0")
    
    # Confirm it was actually created during our session
    if [ "$CSV_MTIME" -gt "$TASK_START" ]; then
        CSV_CREATED_DURING_TASK="true"
    fi
fi

# Check for the saved project file
NG3_PATH="/home/ga/Documents/Energy3D/fpv_design.ng3"
NG3_EXISTS="false"
NG3_CREATED_DURING_TASK="false"
NG3_SIZE="0"

if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$NG3_PATH" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$NG3_PATH" 2>/dev/null || echo "0")
    
    if [ "$NG3_MTIME" -gt "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
fi

# Check if application was actually running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Serialize data locally via JSON tmp file first for safe permission handling
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "csv_exists": $CSV_EXISTS,
    "csv_created_during_task": $CSV_CREATED_DURING_TASK,
    "csv_size_bytes": $CSV_SIZE,
    "csv_lines": $CSV_LINES,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "ng3_size_bytes": $NG3_SIZE,
    "app_was_running": $APP_RUNNING
}
EOF

# Move to final location
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="