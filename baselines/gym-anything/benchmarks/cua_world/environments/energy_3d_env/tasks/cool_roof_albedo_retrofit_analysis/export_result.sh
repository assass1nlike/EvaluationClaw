#!/bin/bash
echo "=== Exporting cool_roof_albedo_retrofit_analysis result ==="

source /workspace/scripts/task_utils.sh || true

# Take final screenshot
take_screenshot /tmp/task_end_screenshot.png

NG3_PATH="/home/ga/Documents/Energy3D/cool_roof_optimized.ng3"
TXT_PATH="/home/ga/Documents/Energy3D/cooling_savings.txt"
START_TS=$(cat /tmp/cool_roof_albedo_retrofit_analysis_start_ts 2>/dev/null || echo "0")

NG3_EXISTS="false"
TXT_EXISTS="false"
NG3_MTIME=0
TXT_MTIME=0

# Export NG3 file if it exists
if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$NG3_PATH" 2>/dev/null || echo "0")
    cp "$NG3_PATH" "/tmp/cool_roof_optimized.ng3" 2>/dev/null || sudo cp "$NG3_PATH" "/tmp/cool_roof_optimized.ng3"
    chmod 644 "/tmp/cool_roof_optimized.ng3" 2>/dev/null || sudo chmod 644 "/tmp/cool_roof_optimized.ng3"
fi

# Export TXT file if it exists
if [ -f "$TXT_PATH" ]; then
    TXT_EXISTS="true"
    TXT_MTIME=$(stat -c %Y "$TXT_PATH" 2>/dev/null || echo "0")
    cp "$TXT_PATH" "/tmp/cooling_savings.txt" 2>/dev/null || sudo cp "$TXT_PATH" "/tmp/cooling_savings.txt"
    chmod 644 "/tmp/cooling_savings.txt" 2>/dev/null || sudo chmod 644 "/tmp/cooling_savings.txt"
fi

# Check if application was still running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Build JSON Result
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "ng3_exists": $NG3_EXISTS,
    "txt_exists": $TXT_EXISTS,
    "ng3_mtime": $NG3_MTIME,
    "txt_mtime": $TXT_MTIME,
    "start_ts": $START_TS,
    "app_running": $APP_RUNNING
}
EOF

# Move to standard location securely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
mv "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo mv "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json

echo "Export complete. Result:"
cat /tmp/task_result.json