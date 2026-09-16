#!/bin/bash
echo "=== Exporting parabolic_trough_process_heat_design result ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Take final screenshot
take_screenshot /tmp/task_end.png

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

FILE_NG3="/home/ga/Documents/Energy3D/trough_plant.ng3"
FILE_TXT="/home/ga/Documents/Energy3D/thermal_yield.txt"

NG3_EXISTS="false"
TXT_EXISTS="false"
NG3_MODIFIED="false"
TXT_MODIFIED="false"

# Check Project File
if [ -f "$FILE_NG3" ]; then
    NG3_EXISTS="true"
    MTIME=$(stat -c %Y "$FILE_NG3" 2>/dev/null || echo "0")
    if [ "$MTIME" -gt "$TASK_START" ]; then 
        NG3_MODIFIED="true"
    fi
    cp "$FILE_NG3" /tmp/trough_plant.ng3
fi

# Check Yield Report File
if [ -f "$FILE_TXT" ]; then
    TXT_EXISTS="true"
    MTIME=$(stat -c %Y "$FILE_TXT" 2>/dev/null || echo "0")
    if [ "$MTIME" -gt "$TASK_START" ]; then 
        TXT_MODIFIED="true"
    fi
    cp "$FILE_TXT" /tmp/thermal_yield.txt
fi

# Check if application was running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Export metadata to JSON
TEMP_JSON=$(mktemp /tmp/task_result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "ng3_exists": $NG3_EXISTS,
    "txt_exists": $TXT_EXISTS,
    "ng3_modified": $NG3_MODIFIED,
    "txt_modified": $TXT_MODIFIED,
    "app_running": $APP_RUNNING,
    "timestamp": "$(date -Iseconds)"
}
EOF

# Move to final location securely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json /tmp/trough_plant.ng3 /tmp/thermal_yield.txt 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "=== Export complete ==="