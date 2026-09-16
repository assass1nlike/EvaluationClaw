#!/bin/bash
echo "=== Exporting residential_solar_payback_period_analysis result ==="

source /workspace/scripts/task_utils.sh

# Capture final screenshot for evidence
take_screenshot /tmp/task_final.png

# Check if the required outputs exist and record metadata
NG3_FILE="/home/ga/Documents/Energy3D/sf_solar_home.ng3"
REPORT_FILE="/home/ga/Documents/Energy3D/payback_report.txt"
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

NG3_EXISTS="false"
if [ -f "$NG3_FILE" ]; then
    NG3_EXISTS="true"
fi

REPORT_EXISTS="false"
REPORT_MTIME="0"
if [ -f "$REPORT_FILE" ]; then
    REPORT_EXISTS="true"
    REPORT_MTIME=$(stat -c %Y "$REPORT_FILE" 2>/dev/null || echo "0")
    
    # Copy report to /tmp for the verifier to safely read it via copy_from_env
    cp "$REPORT_FILE" /tmp/payback_report_result.txt
    chmod 666 /tmp/payback_report_result.txt
fi

APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Create result JSON
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start_time": $TASK_START,
    "ng3_exists": $NG3_EXISTS,
    "report_exists": $REPORT_EXISTS,
    "report_mtime": $REPORT_MTIME,
    "app_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move to final location safely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Result JSON saved to /tmp/task_result.json"
echo "=== Export Complete ==="