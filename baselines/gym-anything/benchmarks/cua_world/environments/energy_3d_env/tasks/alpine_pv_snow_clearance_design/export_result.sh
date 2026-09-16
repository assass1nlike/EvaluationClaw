#!/bin/bash
echo "=== Exporting alpine_pv_snow_clearance_design result ==="
source /workspace/scripts/task_utils.sh || true

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TASK_END=$(date +%s)

# Capture final screenshot
take_screenshot /tmp/task_final.png

NG3_PATH="/home/ga/Documents/Energy3D/alpine_snow_array.ng3"
CSV_PATH="/home/ga/Documents/Energy3D/anchorage_yield.csv"

# Check the modified 3D model export
NG3_EXISTS="false"
NG3_MTIME="0"
NG3_SIZE="0"
if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$NG3_PATH" 2>/dev/null || echo "0")
    NG3_SIZE=$(stat -c %s "$NG3_PATH" 2>/dev/null || echo "0")
fi

# Check the exported yield data
CSV_EXISTS="false"
CSV_MTIME="0"
CSV_SIZE="0"
CSV_LINES="0"
CSV_CONTENT=""
if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    CSV_MTIME=$(stat -c %Y "$CSV_PATH" 2>/dev/null || echo "0")
    CSV_SIZE=$(stat -c %s "$CSV_PATH" 2>/dev/null || echo "0")
    CSV_LINES=$(wc -l < "$CSV_PATH" 2>/dev/null || echo "0")
    # Take first 5 lines as a sample to verify it's actual CSV data
    CSV_CONTENT=$(head -n 5 "$CSV_PATH" | tr '\n' '|' | sed 's/"/\\"/g' 2>/dev/null || echo "")
fi

APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Export all metrics securely to a temp file first
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "app_running": $APP_RUNNING,
    "ng3_exists": $NG3_EXISTS,
    "ng3_mtime": $NG3_MTIME,
    "ng3_size": $NG3_SIZE,
    "csv_exists": $CSV_EXISTS,
    "csv_mtime": $CSV_MTIME,
    "csv_size": $CSV_SIZE,
    "csv_lines": $CSV_LINES,
    "csv_content_sample": "$CSV_CONTENT"
}
EOF

# Move JSON and ensure correct permissions
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
echo "=== Export complete ==="