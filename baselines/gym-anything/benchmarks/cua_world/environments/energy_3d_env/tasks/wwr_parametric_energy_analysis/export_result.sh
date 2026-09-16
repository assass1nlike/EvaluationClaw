#!/bin/bash
echo "=== Exporting wwr_parametric_energy_analysis result ==="

source /workspace/scripts/task_utils.sh

# Record end time and retrieve start time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

# Take final evidence screenshot
take_screenshot /tmp/task_final.png

CSV_PATH="/home/ga/Documents/Energy3D/wwr_results.csv"
NG3_PATH="/home/ga/Documents/Energy3D/chicago_wwr_60.ng3"

# Check CSV output
CSV_EXISTS="false"
CSV_MTIME="0"
if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    CSV_MTIME=$(stat -c %Y "$CSV_PATH")
    # Copy to tmp for verifier extraction
    cp "$CSV_PATH" /tmp/wwr_results.csv
    chmod 666 /tmp/wwr_results.csv
fi

# Check NG3 output
NG3_EXISTS="false"
NG3_MTIME="0"
NG3_SIZE="0"
if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$NG3_PATH")
    NG3_SIZE=$(stat -c %s "$NG3_PATH")
    cp "$NG3_PATH" /tmp/chicago_wwr_60.ng3
    chmod 666 /tmp/chicago_wwr_60.ng3
fi

# Check if application is still running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Create export JSON
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "csv_exists": $CSV_EXISTS,
    "csv_mtime": $CSV_MTIME,
    "ng3_exists": $NG3_EXISTS,
    "ng3_mtime": $NG3_MTIME,
    "ng3_size": $NG3_SIZE,
    "app_running": $APP_RUNNING
}
EOF

# Move and set permissions securely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Export complete. Result saved to /tmp/task_result.json"
cat /tmp/task_result.json