#!/bin/bash
echo "=== Exporting Concentrated Solar Power task result ==="

source /workspace/scripts/task_utils.sh || true

TARGET_FILE="/home/ga/Documents/Energy3D/csp_las_vegas.ng3"
START_TS=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
END_TS=$(date +%s)

# Take a final screenshot
take_screenshot /tmp/task_final.png

FILE_EXISTS="false"
FILE_SIZE=0
FILE_CREATED_DURING_TASK="false"

# Verify if the requested file was saved
if [ -f "$TARGET_FILE" ]; then
    FILE_EXISTS="true"
    FILE_SIZE=$(stat -c %s "$TARGET_FILE" 2>/dev/null || echo "0")
    MTIME=$(stat -c %Y "$TARGET_FILE" 2>/dev/null || echo "0")
    
    if [ "$MTIME" -ge "$START_TS" ]; then
        FILE_CREATED_DURING_TASK="true"
    fi
    
    # Copy the file to /tmp for the verifier to easily read
    cp "$TARGET_FILE" /tmp/project.ng3 2>/dev/null || true
    chmod 666 /tmp/project.ng3 2>/dev/null || true
fi

# Create a summary JSON
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "file_exists": $FILE_EXISTS,
    "file_created_during_task": $FILE_CREATED_DURING_TASK,
    "file_size": $FILE_SIZE,
    "start_time": $START_TS,
    "end_time": $END_TS
}
EOF

# Move JSON into place with wide permissions
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON saved."
cat /tmp/task_result.json
echo "=== Export complete ==="