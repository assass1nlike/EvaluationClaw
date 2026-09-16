#!/bin/bash
echo "=== Exporting ASHRAE Envelope Compliance Result ==="

source /workspace/scripts/task_utils.sh

# Capture final OS screenshot
take_screenshot /tmp/task_final.png

# Get timestamps
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TASK_END=$(date +%s)

NG3_PATH="/home/ga/Documents/Energy3D/compliant_boston_building.ng3"
PNG_PATH="/home/ga/Documents/Energy3D/energy_results.png"

# Evaluate .ng3 output
if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$NG3_PATH")
    NG3_MTIME=$(stat -c %Y "$NG3_PATH")
    if [ "$NG3_MTIME" -gt "$TASK_START" ]; then
        NG3_CREATED="true"
    else
        NG3_CREATED="false"
    fi
else
    NG3_EXISTS="false"
    NG3_SIZE=0
    NG3_CREATED="false"
fi

# Evaluate .png output
if [ -f "$PNG_PATH" ]; then
    PNG_EXISTS="true"
    PNG_SIZE=$(stat -c %s "$PNG_PATH")
    PNG_MTIME=$(stat -c %Y "$PNG_PATH")
    if [ "$PNG_MTIME" -gt "$TASK_START" ]; then
        PNG_CREATED="true"
    else
        PNG_CREATED="false"
    fi
else
    PNG_EXISTS="false"
    PNG_SIZE=0
    PNG_CREATED="false"
fi

# Determine if Energy3D was left running
APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Save structured results to JSON
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED,
    "ng3_size": $NG3_SIZE,
    "png_exists": $PNG_EXISTS,
    "png_created_during_task": $PNG_CREATED,
    "png_size": $PNG_SIZE,
    "app_was_running": $APP_RUNNING
}
EOF

# Safely place the result file with correct permissions
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export Complete ==="