#!/bin/bash
echo "=== Exporting urban_zoning_right_to_light result ==="

# Source utility functions
source /workspace/scripts/task_utils.sh

# Take final screenshot
take_screenshot /tmp/task_final.png ga
sleep 1

START_TIME=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TARGET="/home/ga/Documents/Energy3D/chicago_zoning.ng3"

FILE_EXISTS="false"
FILE_CREATED_DURING_TASK="false"
FILE_SIZE="0"
HAS_CHICAGO_STRING="false"

if [ -f "$TARGET" ]; then
    FILE_EXISTS="true"
    FILE_SIZE=$(stat -c %s "$TARGET" 2>/dev/null || echo "0")
    MTIME=$(stat -c %Y "$TARGET" 2>/dev/null || echo "0")
    
    if [ "$MTIME" -ge "$START_TIME" ]; then
        FILE_CREATED_DURING_TASK="true"
    fi
    
    # Energy3D ng3 files are Java XML encoded. We can search for the location string directly.
    if grep -q -i "chicago" "$TARGET" 2>/dev/null; then
        HAS_CHICAGO_STRING="true"
    fi
fi

# Create a JSON result file
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "file_exists": $FILE_EXISTS,
    "file_created_during_task": $FILE_CREATED_DURING_TASK,
    "file_size_bytes": $FILE_SIZE,
    "has_chicago_string": $HAS_CHICAGO_STRING,
    "start_time": $START_TIME
}
EOF

# Safely move JSON to standard location
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON saved to /tmp/task_result.json"
cat /tmp/task_result.json

echo "=== Export Complete ==="