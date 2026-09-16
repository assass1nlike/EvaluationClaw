#!/bin/bash
echo "=== Exporting Educational Latitude Yield Lab results ==="

source /workspace/scripts/task_utils.sh

# Take final screenshot
take_screenshot /tmp/task_final.png

# Paths and timestamps
CSV_PATH="/home/ga/Documents/Energy3D/latitude_lab_results.csv"
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

CSV_EXISTS="false"
CSV_CREATED_DURING_TASK="false"

# Check if CSV was created and when
if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    CSV_MTIME=$(stat -c %Y "$CSV_PATH" 2>/dev/null || echo "0")
    
    # Check if modified/created after task start
    if [ "$CSV_MTIME" -ge "$TASK_START" ]; then
        CSV_CREATED_DURING_TASK="true"
    fi
    
    # Copy to tmp for easy extraction by python verifier
    cp "$CSV_PATH" /tmp/latitude_lab_results.csv
    chmod 666 /tmp/latitude_lab_results.csv
fi

# Create result JSON
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "csv_exists": $CSV_EXISTS,
    "csv_created_during_task": $CSV_CREATED_DURING_TASK
}
EOF

# Move to final location safely
rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Export complete. Result:"
cat /tmp/task_result.json
echo "=== Export complete ==="