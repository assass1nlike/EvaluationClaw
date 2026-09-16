#!/bin/bash
echo "=== Exporting polar_station_midnight_sun_array task results ==="

source /workspace/scripts/task_utils.sh

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TASK_END=$(date +%s)

CSV_PATH="/home/ga/Documents/Energy3D/midnight_sun_yield.csv"
PROJECT_PATH="/home/ga/Documents/Energy3D/polar_base_solved.ng3"

# Check CSV export
CSV_EXISTS="false"
CSV_MODIFIED="false"
if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    MTIME=$(stat -c %Y "$CSV_PATH" 2>/dev/null || echo "0")
    if [ "$MTIME" -gt "$TASK_START" ]; then
        CSV_MODIFIED="true"
    fi
fi

# Check Project save
PROJECT_EXISTS="false"
PROJECT_MODIFIED="false"
if [ -f "$PROJECT_PATH" ]; then
    PROJECT_EXISTS="true"
    MTIME=$(stat -c %Y "$PROJECT_PATH" 2>/dev/null || echo "0")
    if [ "$MTIME" -gt "$TASK_START" ]; then
        PROJECT_MODIFIED="true"
    fi
fi

APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Final verification screenshot
take_screenshot /tmp/task_final.png

TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "csv_exists": $CSV_EXISTS,
    "csv_modified": $CSV_MODIFIED,
    "project_exists": $PROJECT_EXISTS,
    "project_modified": $PROJECT_MODIFIED,
    "app_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Make sure permissions allow the Python verifier to read it
rm -f /tmp/polar_task_result.json 2>/dev/null || sudo rm -f /tmp/polar_task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/polar_task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/polar_task_result.json
chmod 666 /tmp/polar_task_result.json 2>/dev/null || sudo chmod 666 /tmp/polar_task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/polar_task_result.json"
cat /tmp/polar_task_result.json
echo "=== Export complete ==="