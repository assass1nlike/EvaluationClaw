#!/bin/bash
echo "=== Exporting utility_solar_duck_curve_mitigation results ==="

# Record task end time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

USER_DIR="/home/ga/Documents/Energy3D"
MODEL_FILE="$USER_DIR/duck_curve_mitigated.ng3"
SCREENSHOT_FILE="$USER_DIR/screenshot_daily_yield.png"
REPORT_FILE="$USER_DIR/profile_comparison.txt"

# Helper function to check file stats
check_file() {
    local path="$1"
    if [ -f "$path" ]; then
        local mtime=$(stat -c %Y "$path" 2>/dev/null || echo "0")
        local size=$(stat -c %s "$path" 2>/dev/null || echo "0")
        local created="false"
        if [ "$mtime" -ge "$TASK_START" ]; then
            created="true"
        fi
        echo "{\"exists\": true, \"created_during_task\": $created, \"size\": $size}"
    else
        echo "{\"exists\": false, \"created_during_task\": false, \"size\": 0}"
    fi
}

MODEL_STATS=$(check_file "$MODEL_FILE")
SCREENSHOT_STATS=$(check_file "$SCREENSHOT_FILE")
REPORT_STATS=$(check_file "$REPORT_FILE")

# Read the content of the text report if it exists
REPORT_CONTENT=""
if [ -f "$REPORT_FILE" ]; then
    REPORT_CONTENT=$(cat "$REPORT_FILE" | tr '\n' ' ' | sed 's/"/\\"/g' | sed 's/\\/\\\\/g')
fi

# Take final environment screenshot
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || true

# Create JSON result
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "model_file": $MODEL_STATS,
    "screenshot_file": $SCREENSHOT_STATS,
    "report_file": $REPORT_STATS,
    "report_content": "$REPORT_CONTENT"
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