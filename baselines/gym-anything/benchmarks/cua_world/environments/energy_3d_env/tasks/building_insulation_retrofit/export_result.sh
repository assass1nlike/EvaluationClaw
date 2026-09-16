#!/bin/bash
echo "=== Exporting building_insulation_retrofit result ==="

source /workspace/scripts/task_utils.sh || true

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
USER_DIR="/home/ga/Documents/Energy3D"
OUTPUT_NG3="$USER_DIR/retrofitted_building.ng3"
OUTPUT_PNG="$USER_DIR/retrofit_analysis.png"

# Take final fallback screenshot for safety
take_screenshot /tmp/task_final.png

# Initialize variables
NG3_EXISTS="false"
NG3_CREATED_AFTER="false"
NG3_SIZE="0"

PNG_EXISTS="false"
PNG_CREATED_AFTER="false"
PNG_SIZE="0"

# Check the exported .ng3 file
if [ -f "$OUTPUT_NG3" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$OUTPUT_NG3" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$OUTPUT_NG3" 2>/dev/null || echo "0")
    
    if [ "$NG3_MTIME" -ge "$TASK_START" ]; then
        NG3_CREATED_AFTER="true"
    fi
fi

# Check the exported screenshot file
if [ -f "$OUTPUT_PNG" ]; then
    PNG_EXISTS="true"
    PNG_SIZE=$(stat -c %s "$OUTPUT_PNG" 2>/dev/null || echo "0")
    PNG_MTIME=$(stat -c %Y "$OUTPUT_PNG" 2>/dev/null || echo "0")
    
    if [ "$PNG_MTIME" -ge "$TASK_START" ]; then
        PNG_CREATED_AFTER="true"
    fi
fi

# Create a secure temp file for JSON output
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start_time": $TASK_START,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_after_start": $NG3_CREATED_AFTER,
    "ng3_size_bytes": $NG3_SIZE,
    "png_exists": $PNG_EXISTS,
    "png_created_after_start": $PNG_CREATED_AFTER,
    "png_size_bytes": $PNG_SIZE,
    "final_screenshot_path": "/tmp/task_final.png",
    "export_timestamp": "$(date -Iseconds)"
}
EOF

# Move into final place with proper permissions
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export Complete ==="