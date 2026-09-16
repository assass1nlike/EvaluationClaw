#!/bin/bash
echo "=== Exporting task results ==="

# Source utilities
source /workspace/scripts/task_utils.sh

# Take final screenshot
take_screenshot /tmp/task_final.png

# Get task start time
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

# Define expected output path and starter path
OUT="/home/ga/Documents/Energy3D/hoa_compliant_retrofit.ng3"
STARTER="/home/ga/Documents/Energy3D/building-passive-heating.ng3"

FILE_EXISTS="false"
FILE_CREATED="false"
FILE_SIZE="0"
USED_PATH=""

# Check if agent saved under the requested filename
if [ -f "$OUT" ]; then
    FILE_EXISTS="true"
    USED_PATH="$OUT"
    FILE_SIZE=$(stat -c %s "$OUT" 2>/dev/null || echo "0")
    MTIME=$(stat -c %Y "$OUT" 2>/dev/null || echo "0")
    if [ "$MTIME" -gt "$TASK_START" ]; then
        FILE_CREATED="true"
    fi
    # Copy for python verifier
    cp "$OUT" /tmp/result.ng3 2>/dev/null || true
    chmod 666 /tmp/result.ng3 2>/dev/null || true
    
# Fallback: check if agent just saved over the starter file
elif [ -f "$STARTER" ]; then
    MTIME=$(stat -c %Y "$STARTER" 2>/dev/null || echo "0")
    if [ "$MTIME" -gt "$TASK_START" ]; then
        echo "Note: Agent modified the starter file instead of saving as new."
        FILE_EXISTS="true"
        FILE_CREATED="true"
        USED_PATH="$STARTER"
        FILE_SIZE=$(stat -c %s "$STARTER" 2>/dev/null || echo "0")
        
        # Copy for python verifier
        cp "$STARTER" /tmp/result.ng3 2>/dev/null || true
        chmod 666 /tmp/result.ng3 2>/dev/null || true
    fi
fi

# Check if application is still running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Create JSON result securely via temp file
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "file_exists": $FILE_EXISTS,
    "file_created": $FILE_CREATED,
    "file_size": $FILE_SIZE,
    "used_path": "$USED_PATH",
    "app_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move JSON to accessible location
rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="