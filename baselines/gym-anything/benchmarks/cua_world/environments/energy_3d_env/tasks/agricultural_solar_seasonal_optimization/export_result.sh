#!/bin/bash
echo "=== Exporting task results ==="

source /workspace/scripts/task_utils.sh || true

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
NG3_PATH="/home/ga/Documents/Energy3D/summer_irrigation_array.ng3"
REPORT_PATH="/home/ga/Documents/Energy3D/optimization_report.txt"

NG3_EXISTS="false"
NG3_CREATED_DURING_TASK="false"
REPORT_EXISTS="false"

# Check project file
if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$NG3_PATH" 2>/dev/null || echo "0")
    if [ "$NG3_MTIME" -gt "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
    
    # Extract readable strings from the Java-serialized binary for programmatic verification
    strings "$NG3_PATH" > /tmp/ng3_strings.txt 2>/dev/null || true
else
    echo "" > /tmp/ng3_strings.txt
fi

# Check report file
if [ -f "$REPORT_PATH" ]; then
    REPORT_EXISTS="true"
    cp "$REPORT_PATH" /tmp/agent_report.txt 2>/dev/null || true
else
    echo "" > /tmp/agent_report.txt
fi

# Take final screenshot
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || true

# Create JSON result
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "report_exists": $REPORT_EXISTS,
    "timestamp": "$(date -Iseconds)"
}
EOF

# Move to final location safely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
chmod 666 /tmp/agent_report.txt /tmp/ng3_strings.txt 2>/dev/null || sudo chmod 666 /tmp/agent_report.txt /tmp/ng3_strings.txt 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
echo "=== Export complete ==="