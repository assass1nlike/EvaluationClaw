#!/bin/bash
echo "=== Exporting task results ==="

source /workspace/scripts/task_utils.sh || true

TASK_NAME="winter_solstice_tilt_optimization"
START_TS_FILE="/tmp/${TASK_NAME}_start_ts"
TASK_START=$(cat "$START_TS_FILE" 2>/dev/null || echo "0")
TASK_END=$(date +%s)

USER_DIR="/home/ga/Documents/Energy3D"
EXPECTED_NG3="$USER_DIR/winter_optimized.ng3"
EXPECTED_REPORT="$USER_DIR/winter_report.txt"

# Take final screenshot for VLM evidence
take_screenshot "/tmp/task_final.png"

# Collect file metrics
NG3_EXISTS="false"
NG3_CREATED_DURING_TASK="false"
if [ -f "$EXPECTED_NG3" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$EXPECTED_NG3" 2>/dev/null || echo "0")
    if [ "$NG3_MTIME" -gt "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
fi

REPORT_EXISTS="false"
REPORT_CREATED_DURING_TASK="false"
REPORT_L1=""
REPORT_L2=""
if [ -f "$EXPECTED_REPORT" ]; then
    REPORT_EXISTS="true"
    REPORT_MTIME=$(stat -c %Y "$EXPECTED_REPORT" 2>/dev/null || echo "0")
    if [ "$REPORT_MTIME" -gt "$TASK_START" ]; then
        REPORT_CREATED_DURING_TASK="true"
    fi
    # Safely read first two lines
    REPORT_L1=$(head -n 1 "$EXPECTED_REPORT" | tr -d '\r' | sed 's/"/\\"/g')
    REPORT_L2=$(sed '2q;d' "$EXPECTED_REPORT" | tr -d '\r' | sed 's/"/\\"/g')
fi

# Build JSON Result using a temp file to avoid permission clashing
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "report_exists": $REPORT_EXISTS,
    "report_created_during_task": $REPORT_CREATED_DURING_TASK,
    "report_line_1": "$REPORT_L1",
    "report_line_2": "$REPORT_L2",
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move to standard framework pickup location
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Exported results to /tmp/task_result.json"
cat /tmp/task_result.json

echo "=== Export complete ==="