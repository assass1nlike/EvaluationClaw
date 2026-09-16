#!/bin/bash
echo "=== Exporting datacenter_rooftop_solar_thermal_offset results ==="

# Define paths
TASK_NAME="datacenter_rooftop_solar_thermal_offset"
START_TS=$(cat "/tmp/${TASK_NAME}_start_ts" 2>/dev/null || echo "0")
EXPECTED_CSV="/home/ga/Documents/Energy3D/thermal_offset_results.csv"
EXPECTED_NG3="/home/ga/Documents/Energy3D/datacenter_shaded.ng3"

# Take final screenshot
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || \
    DISPLAY=:1 import -window root /tmp/task_final.png 2>/dev/null || true

# Check if the new project file was created
if [ -f "$EXPECTED_NG3" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$EXPECTED_NG3" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$EXPECTED_NG3" 2>/dev/null || echo "0")
    if [ "$NG3_MTIME" -gt "$START_TS" ]; then
        NG3_CREATED="true"
    else
        NG3_CREATED="false"
    fi
else
    NG3_EXISTS="false"
    NG3_CREATED="false"
    NG3_SIZE="0"
fi

# Check if the CSV results file was exported
if [ -f "$EXPECTED_CSV" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c %s "$EXPECTED_CSV" 2>/dev/null || echo "0")
    CSV_MTIME=$(stat -c %Y "$EXPECTED_CSV" 2>/dev/null || echo "0")
    if [ "$CSV_MTIME" -gt "$START_TS" ]; then
        CSV_CREATED="true"
    else
        CSV_CREATED="false"
    fi
else
    CSV_EXISTS="false"
    CSV_CREATED="false"
    CSV_SIZE="0"
fi

# Check if Energy3D is still running
APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Create JSON result using temp file for safety
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $START_TS,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED,
    "ng3_size_bytes": $NG3_SIZE,
    "csv_exists": $CSV_EXISTS,
    "csv_created_during_task": $CSV_CREATED,
    "csv_size_bytes": $CSV_SIZE,
    "app_was_running": $APP_RUNNING,
    "timestamp": "$(date -Iseconds)"
}
EOF

# Move to final location
rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Results recorded to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="