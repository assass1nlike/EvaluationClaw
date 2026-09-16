#!/bin/bash
echo "=== Exporting BIPV Facade Yield Analysis Result ==="

source /workspace/scripts/task_utils.sh || true

START_TS=$(cat /tmp/task_start_ts 2>/dev/null || echo "0")
DOC_DIR="/home/ga/Documents/Energy3D"
TARGET_NG3="$DOC_DIR/city_block_bipv.ng3"
TARGET_CSV="$DOC_DIR/bipv_yield.csv"

# Take final screenshot
take_screenshot /tmp/task_final.png

# 1. Check NG3 project save
NG3_EXISTS="false"
NG3_CREATED_DURING_TASK="false"
if [ -f "$TARGET_NG3" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$TARGET_NG3" 2>/dev/null || echo "0")
    if [ "$NG3_MTIME" -ge "$START_TS" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
fi

# 2. Check CSV export
CSV_EXISTS="false"
CSV_CREATED_DURING_TASK="false"
CSV_LINES=0
if [ -f "$TARGET_CSV" ]; then
    CSV_EXISTS="true"
    CSV_MTIME=$(stat -c %Y "$TARGET_CSV" 2>/dev/null || echo "0")
    if [ "$CSV_MTIME" -ge "$START_TS" ]; then
        CSV_CREATED_DURING_TASK="true"
    fi
    CSV_LINES=$(wc -l < "$TARGET_CSV" 2>/dev/null || echo "0")
fi

# 3. Application status
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Write results to JSON format
TEMP_JSON=$(mktemp /tmp/bipv_result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "start_ts": $START_TS,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "csv_exists": $CSV_EXISTS,
    "csv_created_during_task": $CSV_CREATED_DURING_TASK,
    "csv_lines": $CSV_LINES,
    "app_running": $APP_RUNNING
}
EOF

# Move temp file to final location handling permissions safely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON written to /tmp/task_result.json"
cat /tmp/task_result.json

echo "=== Export Complete ==="