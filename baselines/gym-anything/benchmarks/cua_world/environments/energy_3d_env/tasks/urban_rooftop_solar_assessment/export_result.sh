#!/bin/bash
echo "=== Exporting task results ==="

# Source utility functions
source /workspace/scripts/task_utils.sh

# Take final screenshot
take_screenshot /tmp/task_final.png

# Get timestamps
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TASK_END=$(date +%s)

NG3_FILE="/home/ga/Documents/Energy3D/city_block_upgraded.ng3"
CSV_FILE="/home/ga/Documents/Energy3D/tallest_building_yield.csv"

# 1. Check if NG3 project was saved
NG3_EXISTS="false"
NG3_CREATED_DURING_TASK="false"
NG3_SIZE="0"
HAS_CHICAGO="false"

if [ -f "$NG3_FILE" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$NG3_FILE" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$NG3_FILE" 2>/dev/null || echo "0")
    
    if [ "$NG3_MTIME" -ge "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
    
    # Energy3D saves Java-serialized binary. Strings inside can be found using the `strings` command.
    if strings "$NG3_FILE" | grep -qi "Chicago"; then
        HAS_CHICAGO="true"
    fi
fi

# 2. Check if CSV file was exported
CSV_EXISTS="false"
CSV_CREATED_DURING_TASK="false"
CSV_SIZE="0"
CSV_LINES="0"

if [ -f "$CSV_FILE" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c %s "$CSV_FILE" 2>/dev/null || echo "0")
    CSV_MTIME=$(stat -c %Y "$CSV_FILE" 2>/dev/null || echo "0")
    
    if [ "$CSV_MTIME" -ge "$TASK_START" ]; then
        CSV_CREATED_DURING_TASK="true"
    fi
    
    CSV_LINES=$(wc -l < "$CSV_FILE" || echo "0")
fi

# Check if application was running
APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Create JSON result securely
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "app_was_running": $APP_RUNNING,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "ng3_size_bytes": $NG3_SIZE,
    "has_chicago_string": $HAS_CHICAGO,
    "csv_exists": $CSV_EXISTS,
    "csv_created_during_task": $CSV_CREATED_DURING_TASK,
    "csv_size_bytes": $CSV_SIZE,
    "csv_lines": $CSV_LINES,
    "screenshot_path": "/tmp/task_final.png"
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