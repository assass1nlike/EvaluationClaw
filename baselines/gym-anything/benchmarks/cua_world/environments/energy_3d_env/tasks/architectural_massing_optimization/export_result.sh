#!/bin/bash
echo "=== Exporting massing optimization result ==="

source /workspace/scripts/task_utils.sh

# Take final screenshot
take_screenshot /tmp/task_end_screenshot.png

TASK_START=$(cat /tmp/task_start_time 2>/dev/null || echo "0")

CSV_PATH="/home/ga/Documents/Energy3D/anchorage_energy.csv"
TXT_PATH="/home/ga/Documents/Energy3D/best_massing.txt"
NG3_PATH="/home/ga/Documents/Energy3D/anchorage-optimized.ng3"

# Verify CSV file
CSV_CREATED="false"
if [ -f "$CSV_PATH" ]; then
    CSV_MTIME=$(stat -c %Y "$CSV_PATH" 2>/dev/null || echo "0")
    if [ "$CSV_MTIME" -ge "$TASK_START" ]; then
        CSV_CREATED="true"
    fi
fi

# Verify TXT file
TXT_CREATED="false"
TXT_CONTENT=""
if [ -f "$TXT_PATH" ]; then
    TXT_MTIME=$(stat -c %Y "$TXT_PATH" 2>/dev/null || echo "0")
    if [ "$TXT_MTIME" -ge "$TASK_START" ]; then
        TXT_CREATED="true"
        # Safely read first 200 chars and escape for JSON
        TXT_CONTENT=$(head -c 200 "$TXT_PATH" | tr -d '\n' | tr -d '\r' | sed 's/"/\\"/g' | sed 's/\\/\\\\/g')
    fi
fi

# Verify NG3 file
NG3_CREATED="false"
if [ -f "$NG3_PATH" ]; then
    NG3_MTIME=$(stat -c %Y "$NG3_PATH" 2>/dev/null || echo "0")
    if [ "$NG3_MTIME" -ge "$TASK_START" ]; then
        NG3_CREATED="true"
    fi
fi

# Create export JSON safely
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "csv_created": $CSV_CREATED,
    "txt_created": $TXT_CREATED,
    "txt_content": "$TXT_CONTENT",
    "ng3_created": $NG3_CREATED
}
EOF

# Move to final location with correct permissions
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="