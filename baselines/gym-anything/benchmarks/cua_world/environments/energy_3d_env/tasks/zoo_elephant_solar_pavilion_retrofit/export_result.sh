#!/bin/bash
echo "=== Exporting Task Results ==="

# Source utilities
source /workspace/scripts/task_utils.sh

# Record task end
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TASK_END=$(date +%s)

# Define target files
USER_DOCS="/home/ga/Documents/Energy3D"
NG3_FILE="$USER_DOCS/phoenix_elephant_pavilion.ng3"
CSV_FILE="$USER_DOCS/elephant_pavilion_yield.csv"

NG3_EXISTS="false"
CSV_EXISTS="false"
CSV_MTIME="0"

# Take final screenshot for visual evidence
take_screenshot /tmp/task_final.png

# Check if the expected modified Energy3D project exists
if [ -f "$NG3_FILE" ]; then
    NG3_EXISTS="true"
    cp "$NG3_FILE" /tmp/phoenix_elephant_pavilion.ng3
    chmod 666 /tmp/phoenix_elephant_pavilion.ng3 2>/dev/null || sudo chmod 666 /tmp/phoenix_elephant_pavilion.ng3
fi

# Check if the expected CSV export exists
if [ -f "$CSV_FILE" ]; then
    CSV_EXISTS="true"
    CSV_MTIME=$(stat -c %Y "$CSV_FILE" 2>/dev/null || echo "0")
    cp "$CSV_FILE" /tmp/elephant_pavilion_yield.csv
    chmod 666 /tmp/elephant_pavilion_yield.csv 2>/dev/null || sudo chmod 666 /tmp/elephant_pavilion_yield.csv
fi

# Write metadata JSON
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "ng3_exists": $NG3_EXISTS,
    "csv_exists": $CSV_EXISTS,
    "csv_mtime": $CSV_MTIME
}
EOF

# Use safe move pattern
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Export result metadata generated."
cat /tmp/task_result.json
echo "=== Export Complete ==="