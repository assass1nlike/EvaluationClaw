#!/bin/bash
echo "=== Exporting aviation_hangar_solar_yield_pruning result ==="

source /workspace/scripts/task_utils.sh || true

TASK_NAME="aviation_hangar_solar_yield_pruning"
START_TS=$(cat /tmp/${TASK_NAME}_start_ts 2>/dev/null || echo "0")
NG3_PATH="/home/ga/Documents/Energy3D/hangar_optimized.ng3"
CSV_PATH="/home/ga/Documents/Energy3D/optimized_yield.csv"

# Take final screenshot as proof of end state
take_screenshot /tmp/task_final.png 2>/dev/null || true

# Check for modified NG3 save file
NG3_EXISTS="false"
NG3_SIZE="0"
NG3_MTIME="0"
if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c%s "$NG3_PATH" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c%Y "$NG3_PATH" 2>/dev/null || echo "0")
fi

# Check for CSV yield export
CSV_EXISTS="false"
CSV_SIZE="0"
CSV_MTIME="0"
if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c%s "$CSV_PATH" 2>/dev/null || echo "0")
    CSV_MTIME=$(stat -c%Y "$CSV_PATH" 2>/dev/null || echo "0")
    
    # Stage CSV in /tmp/ so the verifier can reliably access it via copy_from_env
    cp "$CSV_PATH" /tmp/optimized_yield.csv
    chmod 666 /tmp/optimized_yield.csv
fi

# Create result payload
TEMP_JSON=$(mktemp)
cat > "$TEMP_JSON" << EOF
{
    "start_time": $START_TS,
    "ng3_exists": $NG3_EXISTS,
    "ng3_size": $NG3_SIZE,
    "ng3_mtime": $NG3_MTIME,
    "csv_exists": $CSV_EXISTS,
    "csv_size": $CSV_SIZE,
    "csv_mtime": $CSV_MTIME
}
EOF

# Make result JSON available for verifier
mv "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json

echo "Export complete. Result summary:"
cat /tmp/task_result.json