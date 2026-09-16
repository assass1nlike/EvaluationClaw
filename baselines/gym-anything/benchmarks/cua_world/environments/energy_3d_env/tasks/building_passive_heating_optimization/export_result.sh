#!/bin/bash
echo "=== Exporting building_passive_heating_optimization result ==="

source /workspace/scripts/task_utils.sh

# Record end time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
ORIGINAL_SIZE=$(cat /tmp/original_ng3_size.txt 2>/dev/null || echo "0")

# Take final screenshot
take_screenshot /tmp/task_final.png ga

# Check for modified project file
MODIFIED_NG3="/home/ga/Documents/Energy3D/optimized_passive_heating.ng3"
if [ -f "$MODIFIED_NG3" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$MODIFIED_NG3" 2>/dev/null || echo "0")
    NG3_SIZE=$(stat -c %s "$MODIFIED_NG3" 2>/dev/null || echo "0")
    
    if [ "$NG3_MTIME" -ge "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    else
        NG3_CREATED_DURING_TASK="false"
    fi
else
    NG3_EXISTS="false"
    NG3_CREATED_DURING_TASK="false"
    NG3_SIZE="0"
    NG3_MTIME="0"
fi

# Check for exported CSV file
EXPORTED_CSV="/home/ga/Documents/Energy3D/jan15_energy_load.csv"
if [ -f "$EXPORTED_CSV" ]; then
    CSV_EXISTS="true"
    CSV_MTIME=$(stat -c %Y "$EXPORTED_CSV" 2>/dev/null || echo "0")
    CSV_SIZE=$(stat -c %s "$EXPORTED_CSV" 2>/dev/null || echo "0")
    
    if [ "$CSV_MTIME" -ge "$TASK_START" ]; then
        CSV_CREATED_DURING_TASK="true"
    else
        CSV_CREATED_DURING_TASK="false"
    fi
else
    CSV_EXISTS="false"
    CSV_CREATED_DURING_TASK="false"
    CSV_SIZE="0"
    CSV_MTIME="0"
fi

# Determine if Energy3D is still running
APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Create JSON result structure
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "app_running": $APP_RUNNING,
    "original_ng3_size": $ORIGINAL_SIZE,
    "ng3_file": {
        "exists": $NG3_EXISTS,
        "created_during_task": $NG3_CREATED_DURING_TASK,
        "size_bytes": $NG3_SIZE
    },
    "csv_file": {
        "exists": $CSV_EXISTS,
        "created_during_task": $CSV_CREATED_DURING_TASK,
        "size_bytes": $CSV_SIZE
    }
}
EOF

# Make result readable
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON written to /tmp/task_result.json:"
cat /tmp/task_result.json

echo "=== Export complete ==="