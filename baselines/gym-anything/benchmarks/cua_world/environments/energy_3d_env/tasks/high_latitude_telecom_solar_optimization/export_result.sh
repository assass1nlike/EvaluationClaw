#!/bin/bash
echo "=== Exporting high_latitude_telecom_solar_optimization result ==="

source /workspace/scripts/task_utils.sh

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TASK_END=$(date +%s)

# Take final screenshot
take_screenshot /tmp/task_final.png

USER_DIR="/home/ga/Documents/Energy3D"
EXPECTED_NG3="$USER_DIR/anchorage_telecom_site.ng3"
EXPECTED_CSV="$USER_DIR/anchorage_winter_yield.csv"

# Initialize variables
NG3_EXISTS="false"
NG3_SIZE="0"
NG3_CREATED_DURING_TASK="false"

CSV_EXISTS="false"
CSV_SIZE="0"
CSV_CREATED_DURING_TASK="false"

# Check NG3 file
if [ -f "$EXPECTED_NG3" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$EXPECTED_NG3" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$EXPECTED_NG3" 2>/dev/null || echo "0")
    
    if [ "$NG3_MTIME" -ge "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
fi

# Check CSV file
if [ -f "$EXPECTED_CSV" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c %s "$EXPECTED_CSV" 2>/dev/null || echo "0")
    CSV_MTIME=$(stat -c %Y "$EXPECTED_CSV" 2>/dev/null || echo "0")
    
    if [ "$CSV_MTIME" -ge "$TASK_START" ]; then
        CSV_CREATED_DURING_TASK="true"
    fi
    
    # Copy to /tmp so the verifier can easily read it via copy_from_env
    cp "$EXPECTED_CSV" /tmp/yield_export.csv 2>/dev/null || true
    chmod 666 /tmp/yield_export.csv 2>/dev/null || true
fi

# Check if Energy3D is still running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Create result JSON
TEMP_JSON=$(mktemp /tmp/task_result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "app_was_running": $APP_RUNNING,
    "ng3_exists": $NG3_EXISTS,
    "ng3_size_bytes": $NG3_SIZE,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "csv_exists": $CSV_EXISTS,
    "csv_size_bytes": $CSV_SIZE,
    "csv_created_during_task": $CSV_CREATED_DURING_TASK
}
EOF

# Move to final location safely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "=== Export complete ==="
cat /tmp/task_result.json