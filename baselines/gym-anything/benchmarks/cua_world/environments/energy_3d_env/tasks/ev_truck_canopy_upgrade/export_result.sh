#!/bin/bash
echo "=== Exporting ev_truck_canopy_upgrade task result ==="

source /workspace/scripts/task_utils.sh || true

# Take final screenshot
take_screenshot /tmp/task_final.png

# Get timestamps
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TASK_END=$(date +%s)

EXPANDED_FILE="/home/ga/Documents/Energy3D/ev_canopy_expanded.ng3"
SUMMARY_FILE="/home/ga/Documents/Energy3D/yield_summary.txt"

NG3_EXISTS="false"
NG3_MTIME="0"
if [ -f "$EXPANDED_FILE" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$EXPANDED_FILE" 2>/dev/null || echo "0")
    
    # Copy file to /tmp so verifier can read it easily via copy_from_env
    cp "$EXPANDED_FILE" /tmp/ev_canopy_expanded.ng3
    chmod 666 /tmp/ev_canopy_expanded.ng3 2>/dev/null || sudo chmod 666 /tmp/ev_canopy_expanded.ng3 2>/dev/null || true
fi

TXT_EXISTS="false"
TXT_CONTENT=""
if [ -f "$SUMMARY_FILE" ]; then
    TXT_EXISTS="true"
    # Extract text content safely to JSON (first 200 chars to avoid massive payloads)
    TXT_CONTENT=$(head -c 200 "$SUMMARY_FILE" | tr -d '\n' | tr -d '\r' | sed 's/"/\\"/g' | sed 's/\\/\\\\/g')
fi

# Check if application is running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Create result JSON safely
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "ng3_exists": $NG3_EXISTS,
    "ng3_mtime": $NG3_MTIME,
    "txt_exists": $TXT_EXISTS,
    "txt_content": "$TXT_CONTENT",
    "app_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move to final location
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Exported results successfully."
cat /tmp/task_result.json
echo "=== Export Complete ==="