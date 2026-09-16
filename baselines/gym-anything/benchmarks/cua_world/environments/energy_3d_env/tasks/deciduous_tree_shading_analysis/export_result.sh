#!/bin/bash
echo "=== Exporting deciduous_tree_shading_analysis result ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="deciduous_tree_shading_analysis"
START_TS_FILE="/tmp/${TASK_NAME}_start_ts"
TASK_START=$(cat "$START_TS_FILE" 2>/dev/null || echo "0")

OUTPUT_NG3="/home/ga/Documents/Energy3D/shaded_building.ng3"
OUTPUT_CSV="/home/ga/Documents/Energy3D/summer_analysis.csv"

# Take final screenshot
take_screenshot /tmp/task_final.png

# Check if model was saved
NG3_EXISTS="false"
NG3_CREATED_AFTER_START="false"
NG3_SIZE="0"
if [ -f "$OUTPUT_NG3" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$OUTPUT_NG3" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$OUTPUT_NG3" 2>/dev/null || echo "0")
    if [ "$NG3_MTIME" -ge "$TASK_START" ]; then
        NG3_CREATED_AFTER_START="true"
    fi
fi

# Check if CSV was exported
CSV_EXISTS="false"
CSV_CREATED_AFTER_START="false"
CSV_SIZE="0"
if [ -f "$OUTPUT_CSV" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c %s "$OUTPUT_CSV" 2>/dev/null || echo "0")
    CSV_MTIME=$(stat -c %Y "$OUTPUT_CSV" 2>/dev/null || echo "0")
    if [ "$CSV_MTIME" -ge "$TASK_START" ]; then
        CSV_CREATED_AFTER_START="true"
    fi
fi

# Create result JSON
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start_ts": $TASK_START,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_after_start": $NG3_CREATED_AFTER_START,
    "ng3_size_bytes": $NG3_SIZE,
    "csv_exists": $CSV_EXISTS,
    "csv_created_after_start": $CSV_CREATED_AFTER_START,
    "csv_size_bytes": $CSV_SIZE,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move to standard verification location
rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON saved to /tmp/task_result.json"
cat /tmp/task_result.json

echo "=== Export Complete ==="