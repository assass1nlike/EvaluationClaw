#!/bin/bash
echo "=== Exporting task results ==="

source /workspace/scripts/task_utils.sh || true

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TASK_END=$(date +%s)

# Take final screenshot as evidence
take_screenshot /tmp/task_final.png

# Check for the expected output file in possible locations
OUTPUT_EXISTS="false"
FILE_CREATED_DURING_TASK="false"
OUTPUT_SIZE="0"
FOUND_PATH=""

POSSIBLE_PATHS=(
    "/home/ga/Documents/Energy3D/dish_array_upgrade.ng3"
    "/home/ga/dish_array_upgrade.ng3"
    "/home/ga/Documents/dish_array_upgrade.ng3"
)

for path in "${POSSIBLE_PATHS[@]}"; do
    if [ -f "$path" ]; then
        OUTPUT_EXISTS="true"
        FOUND_PATH="$path"
        OUTPUT_SIZE=$(stat -c %s "$path" 2>/dev/null || echo "0")
        OUTPUT_MTIME=$(stat -c %Y "$path" 2>/dev/null || echo "0")
        
        if [ "$OUTPUT_MTIME" -ge "$TASK_START" ]; then
            FILE_CREATED_DURING_TASK="true"
        fi
        break
    fi
done

# Try to extract strings to see if ParabolicDish references exist 
# (Energy3D ng3 is Java serialized binary, but class names usually exist in string pool)
DISH_STRINGS="0"
PANEL_STRINGS="0"
if [ "$OUTPUT_EXISTS" = "true" ]; then
    DISH_STRINGS=$(strings "$FOUND_PATH" 2>/dev/null | grep -i "ParabolicDish" | wc -l || echo "0")
    PANEL_STRINGS=$(strings "$FOUND_PATH" 2>/dev/null | grep -i "SolarPanel" | wc -l || echo "0")
fi

# Create JSON result safely
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "output_exists": $OUTPUT_EXISTS,
    "found_path": "$FOUND_PATH",
    "file_created_during_task": $FILE_CREATED_DURING_TASK,
    "output_size_bytes": $OUTPUT_SIZE,
    "programmatic_hints": {
        "dish_string_count": $DISH_STRINGS,
        "panel_string_count": $PANEL_STRINGS
    }
}
EOF

# Move to final destination
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json

echo "=== Export complete ==="