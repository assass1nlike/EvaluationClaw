#!/bin/bash
echo "=== Exporting Historic Preservation Solar Retrofit Result ==="

source /workspace/scripts/task_utils.sh

# Take final screenshot
take_screenshot /tmp/task_final.png

START_TS=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
USER_DIR="/home/ga/Documents/Energy3D"
OUTPUT_NG3="$USER_DIR/historic_retrofit.ng3"
OUTPUT_CSV="$USER_DIR/historic_solar_yield.csv"

# Check Project File (.ng3)
NG3_EXISTS="false"
NG3_CREATED_DURING_TASK="false"
NG3_SIZE=0

if [ -f "$OUTPUT_NG3" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$OUTPUT_NG3" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$OUTPUT_NG3" 2>/dev/null || echo "0")
    
    if [ "$NG3_MTIME" -ge "$START_TS" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
fi

# Check Exported Data File (.csv)
CSV_EXISTS="false"
CSV_CREATED_DURING_TASK="false"
CSV_SIZE=0
CSV_LINE_COUNT=0

if [ -f "$OUTPUT_CSV" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c %s "$OUTPUT_CSV" 2>/dev/null || echo "0")
    CSV_MTIME=$(stat -c %Y "$OUTPUT_CSV" 2>/dev/null || echo "0")
    CSV_LINE_COUNT=$(wc -l < "$OUTPUT_CSV" 2>/dev/null || echo "0")
    
    if [ "$CSV_MTIME" -ge "$START_TS" ]; then
        CSV_CREATED_DURING_TASK="true"
    fi
fi

# Check if Energy3D was running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Generate JSON result
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start_time": $START_TS,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "ng3_size_bytes": $NG3_SIZE,
    "csv_exists": $CSV_EXISTS,
    "csv_created_during_task": $CSV_CREATED_DURING_TASK,
    "csv_size_bytes": $CSV_SIZE,
    "csv_line_count": $CSV_LINE_COUNT,
    "app_running": $APP_RUNNING
}
EOF

# Safely move JSON result
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Export details saved to /tmp/task_result.json"
cat /tmp/task_result.json

echo "=== Export complete ==="