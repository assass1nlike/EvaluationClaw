#!/bin/bash
echo "=== Exporting high_wind_landscape_solar_array_redesign result ==="

source /workspace/scripts/task_utils.sh

# Record timestamps
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TASK_END=$(date +%s)

TARGET_NG3="/home/ga/Documents/Energy3D/miami_landscape_array.ng3"
TARGET_CSV="/home/ga/Documents/Energy3D/miami_annual_yield.csv"

# Check .ng3 modified state
NG3_EXISTS="false"
NG3_MTIME="0"
NG3_SIZE="0"
HAS_MIAMI_STRING="false"

if [ -f "$TARGET_NG3" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$TARGET_NG3" 2>/dev/null || echo "0")
    NG3_SIZE=$(stat -c %s "$TARGET_NG3" 2>/dev/null || echo "0")
    
    # Simple binary/text parse to check if 'Miami' is inside the file
    if grep -qa "Miami" "$TARGET_NG3" 2>/dev/null; then
        HAS_MIAMI_STRING="true"
    fi
fi

# Check .csv export state
CSV_EXISTS="false"
CSV_MTIME="0"
CSV_SIZE="0"
CSV_LINES="0"

if [ -f "$TARGET_CSV" ]; then
    CSV_EXISTS="true"
    CSV_MTIME=$(stat -c %Y "$TARGET_CSV" 2>/dev/null || echo "0")
    CSV_SIZE=$(stat -c %s "$TARGET_CSV" 2>/dev/null || echo "0")
    CSV_LINES=$(wc -l < "$TARGET_CSV" 2>/dev/null || echo "0")
fi

# Check if Energy3D was running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Take final evidence screenshot
take_screenshot /tmp/task_final.png ga

# Create structured JSON payload (safely with tmp file)
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "ng3_exists": $NG3_EXISTS,
    "ng3_mtime": $NG3_MTIME,
    "ng3_size": $NG3_SIZE,
    "has_miami_string": $HAS_MIAMI_STRING,
    "csv_exists": $CSV_EXISTS,
    "csv_mtime": $CSV_MTIME,
    "csv_size": $CSV_SIZE,
    "csv_lines": $CSV_LINES,
    "app_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move payload over safely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON saved to /tmp/task_result.json"
cat /tmp/task_result.json

echo "=== Export complete ==="