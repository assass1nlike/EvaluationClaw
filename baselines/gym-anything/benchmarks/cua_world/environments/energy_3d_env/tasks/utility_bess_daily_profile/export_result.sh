#!/bin/bash
echo "=== Exporting utility_bess_daily_profile task results ==="

source /workspace/scripts/task_utils.sh

# Take final screenshot to capture the ending UI state
take_screenshot /tmp/task_final.png

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
NG3_PATH="/home/ga/Documents/Energy3D/phoenix_bess_array.ng3"
CSV_PATH="/home/ga/Documents/Energy3D/solstice_hourly_profile.csv"
TXT_PATH="/home/ga/Documents/Energy3D/peak_charge_hour.txt"

# Check for saved .ng3 project
NG3_EXISTS="false"
if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    cp "$NG3_PATH" /tmp/phoenix_bess_array.ng3
fi

# Check for CSV artifact
CSV_EXISTS="false"
if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    cp "$CSV_PATH" /tmp/solstice_hourly_profile.csv
fi

# Check for text document
TXT_EXISTS="false"
if [ -f "$TXT_PATH" ]; then
    TXT_EXISTS="true"
    cp "$TXT_PATH" /tmp/peak_charge_hour.txt
fi

# Combine the findings into a JSON output block
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "ng3_exists": $NG3_EXISTS,
    "csv_exists": $CSV_EXISTS,
    "txt_exists": $TXT_EXISTS,
    "timestamp": "$(date -Iseconds)"
}
EOF

# Move payload to a predictable location the verifier checks
rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "=== Export complete ==="