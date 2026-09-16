#!/bin/bash
echo "=== Exporting task results ==="

source /workspace/scripts/task_utils.sh

# Record task end time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

OUTPUT_CSV="/home/ga/Documents/Energy3D/supermarket_yield.csv"
OUTPUT_NG3="/home/ga/Documents/Energy3D/supermarket_rtu_layout.ng3"

# Check CSV
CSV_EXISTS="false"
CSV_CREATED="false"
CSV_SIZE="0"

if [ -f "$OUTPUT_CSV" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c %s "$OUTPUT_CSV" 2>/dev/null || echo "0")
    CSV_MTIME=$(stat -c %Y "$OUTPUT_CSV" 2>/dev/null || echo "0")
    if [ "$CSV_MTIME" -ge "$TASK_START" ]; then
        CSV_CREATED="true"
    fi
    # Copy for verifier
    cp "$OUTPUT_CSV" /tmp/supermarket_yield.csv
    chmod 666 /tmp/supermarket_yield.csv
fi

# Check NG3
NG3_EXISTS="false"
NG3_CREATED="false"
NG3_SIZE="0"

if [ -f "$OUTPUT_NG3" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$OUTPUT_NG3" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$OUTPUT_NG3" 2>/dev/null || echo "0")
    if [ "$NG3_MTIME" -ge "$TASK_START" ]; then
        NG3_CREATED="true"
    fi
fi

# Take final screenshot
take_screenshot /tmp/task_final.png

# Write result JSON
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "csv_exists": $CSV_EXISTS,
    "csv_created": $CSV_CREATED,
    "csv_size": $CSV_SIZE,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created": $NG3_CREATED,
    "ng3_size": $NG3_SIZE,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json

echo "Result JSON saved."
cat /tmp/task_result.json

echo "=== Export complete ==="