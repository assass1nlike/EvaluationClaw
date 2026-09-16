#!/bin/bash
echo "=== Exporting urban_microgrid_shading_analysis task results ==="

# Source shared utilities
source /workspace/scripts/task_utils.sh

# Take final screenshot
take_screenshot /tmp/task_final.png

# Record times
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

# Check for the expected output file
OUTPUT_PATH="/home/ga/Documents/Energy3D/chicago_microgrid.ng3"
FILE_EXISTS="false"
FILE_MTIME="0"
FILE_SIZE="0"

if [ -f "$OUTPUT_PATH" ]; then
    FILE_EXISTS="true"
    FILE_MTIME=$(stat -c %Y "$OUTPUT_PATH" 2>/dev/null || echo "0")
    FILE_SIZE=$(stat -c %s "$OUTPUT_PATH" 2>/dev/null || echo "0")
    
    # Copy the file to /tmp so the verifier can easily grab it via copy_from_env
    cp "$OUTPUT_PATH" /tmp/exported_microgrid.ng3
    chmod 666 /tmp/exported_microgrid.ng3
else
    # If not found at the exact path, look for it in the Documents folder generally
    FALLBACK=$(find /home/ga/Documents -name "chicago_microgrid.ng3" | head -n 1)
    if [ -n "$FALLBACK" ]; then
        FILE_EXISTS="true"
        FILE_MTIME=$(stat -c %Y "$FALLBACK" 2>/dev/null || echo "0")
        FILE_SIZE=$(stat -c %s "$FALLBACK" 2>/dev/null || echo "0")
        cp "$FALLBACK" /tmp/exported_microgrid.ng3
        chmod 666 /tmp/exported_microgrid.ng3
    fi
fi

# Check if application was running
APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Create JSON result
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "file_exists": $FILE_EXISTS,
    "file_mtime": $FILE_MTIME,
    "file_size": $FILE_SIZE,
    "app_was_running": $APP_RUNNING
}
EOF

# Move to final location
rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
echo "=== Export complete ==="