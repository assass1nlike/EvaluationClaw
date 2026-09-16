#!/bin/bash
echo "=== Exporting desert_solar_temp_coefficient_upgrade results ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task end time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

# Take final screenshot
take_screenshot /tmp/task_final.png

USER_DIR="/home/ga/Documents/Energy3D"
EXPECTED_OUT="$USER_DIR/hjt_upgrade_phoenix.ng3"
EXPECTED_REPORT="$USER_DIR/yield_report.txt"

# Check if expected project file was saved
OUT_EXISTS="false"
OUT_CREATED_DURING_TASK="false"
OUT_SIZE="0"

if [ -f "$EXPECTED_OUT" ]; then
    OUT_EXISTS="true"
    OUT_MTIME=$(stat -c %Y "$EXPECTED_OUT" 2>/dev/null || echo "0")
    if [ "$OUT_MTIME" -ge "$TASK_START" ]; then
        OUT_CREATED_DURING_TASK="true"
    fi
    OUT_SIZE=$(stat -c %s "$EXPECTED_OUT" 2>/dev/null || echo "0")
fi

# Check if yield report exists and read content
REPORT_EXISTS="false"
REPORT_CREATED_DURING_TASK="false"
REPORT_CONTENT=""

if [ -f "$EXPECTED_REPORT" ]; then
    REPORT_EXISTS="true"
    REPORT_MTIME=$(stat -c %Y "$EXPECTED_REPORT" 2>/dev/null || echo "0")
    if [ "$REPORT_MTIME" -ge "$TASK_START" ]; then
        REPORT_CREATED_DURING_TASK="true"
    fi
    # Read up to 500 chars to avoid massive file dumps if agent misbehaves
    REPORT_CONTENT=$(head -c 500 "$EXPECTED_REPORT" | tr -d '\000-\011\013\014\016-\037' | sed 's/"/\\"/g')
fi

# Check if application was running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Create JSON result (use temp file for permission safety)
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "output_ng3_exists": $OUT_EXISTS,
    "output_ng3_created_during_task": $OUT_CREATED_DURING_TASK,
    "output_ng3_size_bytes": $OUT_SIZE,
    "report_exists": $REPORT_EXISTS,
    "report_created_during_task": $REPORT_CREATED_DURING_TASK,
    "report_content": "$REPORT_CONTENT",
    "app_was_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move to final location with permission handling
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="