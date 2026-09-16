#!/bin/bash
echo "=== Exporting height_constrained_urban_solar_retrofit result ==="

source /workspace/scripts/task_utils.sh || true

TASK_NAME="height_constrained_urban_solar_retrofit"
START_TS=$(cat "/tmp/${TASK_NAME}_start_ts" 2>/dev/null || echo "0")
NG3_FILE="/home/ga/Documents/Energy3D/low_profile_array.ng3"
REPORT_FILE="/home/ga/Documents/Energy3D/yield_report.txt"

# Take final screenshot for visual analysis
take_screenshot /tmp/task_end.png || true

# Check modified project file (.ng3)
NG3_EXISTS="false"
NG3_CREATED_AFTER="false"
if [ -f "$NG3_FILE" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$NG3_FILE" 2>/dev/null || echo "0")
    if [ "$NG3_MTIME" -gt "$START_TS" ]; then
        NG3_CREATED_AFTER="true"
    fi
fi

# Check text report file
REPORT_EXISTS="false"
REPORT_CREATED_AFTER="false"
REPORT_CONTENT=""
if [ -f "$REPORT_FILE" ]; then
    REPORT_EXISTS="true"
    REPORT_MTIME=$(stat -c %Y "$REPORT_FILE" 2>/dev/null || echo "0")
    if [ "$REPORT_MTIME" -gt "$START_TS" ]; then
        REPORT_CREATED_AFTER="true"
    fi
    # Only read alphanumeric and basic punctuation, avoiding any characters that could break JSON
    REPORT_CONTENT=$(cat "$REPORT_FILE" | head -n 5 | tr -d '\n' | tr -dc '[:alnum:]. ')
fi

# Detect application state
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Write results to JSON temp file securely
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start_ts": $START_TS,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_after": $NG3_CREATED_AFTER,
    "report_exists": $REPORT_EXISTS,
    "report_created_after": $REPORT_CREATED_AFTER,
    "report_content": "$REPORT_CONTENT",
    "app_was_running": $APP_RUNNING,
    "timestamp": "$(date -Iseconds)"
}
EOF

# Move payload over handling permissions
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result safely saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="