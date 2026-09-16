#!/bin/bash
echo "=== Exporting task results ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_START=$(cat /tmp/task_start_ts 2>/dev/null || echo "0")
TASK_END=$(date +%s)

NG3_PATH="/home/ga/Documents/Energy3D/optimized_array.ng3"
CSV_PATH="/home/ga/Documents/Energy3D/winter_yield_optimized.csv"

# Take final screenshot
take_screenshot /tmp/task_final.png

# Check if optimized NG3 file was created/saved
NG3_EXISTS="false"
NG3_SIZE="0"
NG3_CREATED_DURING_TASK="false"

if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$NG3_PATH" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$NG3_PATH" 2>/dev/null || echo "0")
    
    if [ "$NG3_MTIME" -ge "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
fi

# Check if CSV file was exported
CSV_EXISTS="false"
CSV_SIZE="0"
CSV_CREATED_DURING_TASK="false"
CSV_CONTENT_SNIPPET=""

if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c %s "$CSV_PATH" 2>/dev/null || echo "0")
    CSV_MTIME=$(stat -c %Y "$CSV_PATH" 2>/dev/null || echo "0")
    
    if [ "$CSV_MTIME" -ge "$TASK_START" ]; then
        CSV_CREATED_DURING_TASK="true"
    fi
    
    # Grab the first few lines of the CSV to embed in JSON for basic validation
    # Base64 encode to avoid JSON formatting issues with newlines/quotes
    CSV_CONTENT_SNIPPET=$(head -n 5 "$CSV_PATH" | base64 -w 0 2>/dev/null || echo "")
fi

# Check if application was running
APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Create JSON result
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "app_was_running": $APP_RUNNING,
    "ng3_file": {
        "exists": $NG3_EXISTS,
        "size_bytes": $NG3_SIZE,
        "created_during_task": $NG3_CREATED_DURING_TASK
    },
    "csv_file": {
        "exists": $CSV_EXISTS,
        "size_bytes": $CSV_SIZE,
        "created_during_task": $CSV_CREATED_DURING_TASK,
        "content_base64": "$CSV_CONTENT_SNIPPET"
    }
}
EOF

# Move to final location safely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Export complete. Result JSON:"
cat /tmp/task_result.json
echo "=== Export complete ==="