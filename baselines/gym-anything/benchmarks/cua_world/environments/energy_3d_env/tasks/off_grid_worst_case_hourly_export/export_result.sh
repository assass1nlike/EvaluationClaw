#!/bin/bash
echo "=== Exporting task results ==="

source /workspace/scripts/task_utils.sh

# Capture final screenshot
take_screenshot /tmp/task_final.png

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TASK_END=$(date +%s)

NG3_PATH="/home/ga/Documents/Energy3D/boston_winter.ng3"
CSV_PATH="/home/ga/Documents/Energy3D/boston_dec21_hourly.csv"

NG3_EXISTS="false"
NG3_CREATED="false"
if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    MTIME=$(stat -c %Y "$NG3_PATH" 2>/dev/null || echo "0")
    if [ "$MTIME" -gt "$TASK_START" ]; then
        NG3_CREATED="true"
    fi
fi

CSV_EXISTS="false"
CSV_CREATED="false"
if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    MTIME=$(stat -c %Y "$CSV_PATH" 2>/dev/null || echo "0")
    if [ "$MTIME" -gt "$TASK_START" ]; then
        CSV_CREATED="true"
    fi
fi

# Create export JSON safely handling permissions
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED,
    "csv_exists": $CSV_EXISTS,
    "csv_created_during_task": $CSV_CREATED,
    "task_start": $TASK_START,
    "task_end": $TASK_END
}
EOF

rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Export Complete."