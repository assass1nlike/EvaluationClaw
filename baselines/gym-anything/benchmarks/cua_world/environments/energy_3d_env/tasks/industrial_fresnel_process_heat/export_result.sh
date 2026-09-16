#!/bin/bash
echo "=== Exporting industrial_fresnel_process_heat result ==="

source /workspace/scripts/task_utils.sh

# Take final screenshot as primary VLM evidence
take_screenshot /tmp/fresnel_final.png

# Check for expected output files
NG3_PATH="/home/ga/Documents/Energy3D/fresnel_plant.ng3"
CSV_PATH="/home/ga/Documents/Energy3D/fresnel_output.csv"

START_TS=$(cat /tmp/industrial_fresnel_process_heat_start_ts 2>/dev/null || echo "0")

# Check NG3 project save
NG3_EXISTS="false"
NG3_SIZE=0
if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$NG3_PATH")
fi

# Check CSV data export
CSV_EXISTS="false"
CSV_SIZE=0
CSV_LINES=0
CSV_HAS_DATA="false"

if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c %s "$CSV_PATH")
    CSV_LINES=$(wc -l < "$CSV_PATH")
    
    # Check if there is any non-zero numeric data in the CSV
    # (Energy3D yields contain digits greater than 0 if a target exists and produces energy)
    if grep -q -E "[1-9][0-9]*\.?[0-9]*" "$CSV_PATH"; then
        CSV_HAS_DATA="true"
    fi
fi

# Check if application is still running
APP_RUNNING="false"
if find_energy3d_window > /dev/null; then
    APP_RUNNING="true"
fi

# Create export payload
TEMP_JSON=$(mktemp /tmp/fresnel_result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "ng3_exists": $NG3_EXISTS,
    "ng3_size_bytes": $NG3_SIZE,
    "csv_exists": $CSV_EXISTS,
    "csv_size_bytes": $CSV_SIZE,
    "csv_lines": $CSV_LINES,
    "csv_has_data": $CSV_HAS_DATA,
    "app_running": $APP_RUNNING,
    "task_start_ts": $START_TS,
    "timestamp": "$(date -Iseconds)"
}
EOF

# Move payload to standardized location
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Result JSON saved to /tmp/task_result.json"
cat /tmp/task_result.json

echo "=== Export complete ==="