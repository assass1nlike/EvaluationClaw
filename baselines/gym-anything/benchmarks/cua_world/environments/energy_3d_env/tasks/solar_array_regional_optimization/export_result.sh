#!/bin/bash
echo "=== Exporting solar_array_regional_optimization result ==="

source /workspace/scripts/task_utils.sh

# Take final state screenshot
take_screenshot /tmp/task_final.png

TARGET_FILE="/home/ga/Documents/Energy3D/phoenix-solar-array.ng3"
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

# Initialize verification flags
FILE_EXISTS="false"
CREATED_DURING_TASK="false"
FILE_SIZE="0"
HAS_PHOENIX_STRING="false"
HAS_PANEL_STRING="false"

if [ -f "$TARGET_FILE" ]; then
    FILE_EXISTS="true"
    FILE_SIZE=$(stat -c %s "$TARGET_FILE" 2>/dev/null || echo "0")
    FILE_MTIME=$(stat -c %Y "$TARGET_FILE" 2>/dev/null || echo "0")
    
    # Check anti-gaming timestamp
    if [ "$FILE_MTIME" -gt "$TASK_START" ]; then
        CREATED_DURING_TASK="true"
    fi

    # Energy3D saves as Java serialized binary format.
    # We can extract plaintext strings using the 'strings' utility to verify string-based attributes.
    if strings "$TARGET_FILE" 2>/dev/null | grep -qi "Phoenix"; then
        HAS_PHOENIX_STRING="true"
    fi
    
    if strings "$TARGET_FILE" 2>/dev/null | grep -qi "SPR-X21"; then
        HAS_PANEL_STRING="true"
    fi
fi

# Create a JSON result file
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "file_exists": $FILE_EXISTS,
    "created_during_task": $CREATED_DURING_TASK,
    "file_size_bytes": $FILE_SIZE,
    "has_phoenix_string": $HAS_PHOENIX_STRING,
    "has_panel_string": $HAS_PANEL_STRING,
    "task_start_time": $TASK_START
}
EOF

# Move to final location safely
rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Export complete. Results saved to /tmp/task_result.json."
cat /tmp/task_result.json