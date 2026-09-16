#!/bin/bash
echo "=== Exporting Task Results ==="

# Record task end time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

USER_DIR="/home/ga/Documents/Energy3D"
EXPECTED_CSV="$USER_DIR/west_facing_yield.csv"
EXPECTED_NG3="$USER_DIR/tou_optimized.ng3"

# Check if Energy3D is still running
APP_RUNNING="false"
if pgrep -f "Energy3D" > /dev/null; then
    APP_RUNNING="true"
fi

# Take final screenshot
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || \
    DISPLAY=:1 import -window root /tmp/task_final.png 2>/dev/null || true

# --- Evaluate NG3 Project File ---
NG3_EXISTS="false"
NG3_CREATED_DURING_TASK="false"
NG3_SIZE=0

if [ -f "$EXPECTED_NG3" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$EXPECTED_NG3" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$EXPECTED_NG3" 2>/dev/null || echo "0")
    if [ "$NG3_MTIME" -gt "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
fi

# --- Evaluate CSV Yield File ---
CSV_EXISTS="false"
CSV_CREATED_DURING_TASK="false"
CSV_SIZE=0

if [ -f "$EXPECTED_CSV" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c %s "$EXPECTED_CSV" 2>/dev/null || echo "0")
    CSV_MTIME=$(stat -c %Y "$EXPECTED_CSV" 2>/dev/null || echo "0")
    if [ "$CSV_MTIME" -gt "$TASK_START" ]; then
        CSV_CREATED_DURING_TASK="true"
    fi
    
    # Copy CSV to a location the verifier can easily grab
    cp "$EXPECTED_CSV" /tmp/west_facing_yield.csv
    chmod 666 /tmp/west_facing_yield.csv
fi

# Construct Result JSON
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "app_running": $APP_RUNNING,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "ng3_size_bytes": $NG3_SIZE,
    "csv_exists": $CSV_EXISTS,
    "csv_created_during_task": $CSV_CREATED_DURING_TASK,
    "csv_size_bytes": $CSV_SIZE
}
EOF

# Safely move JSON to final location
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Results successfully exported."
cat /tmp/task_result.json

echo "=== Export Complete ==="