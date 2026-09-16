#!/bin/bash
echo "=== Exporting railway_corridor_vertical_solar_fence result ==="

source /workspace/scripts/task_utils.sh || true

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TASK_END=$(date +%s)

# Capture final state screenshot
take_screenshot /tmp/task_final.png ga

USER_DIR="/home/ga/Documents/Energy3D"
NG3_FILE="$USER_DIR/vertical_solar_fence.ng3"
TXT_FILE="$USER_DIR/fence_yield.txt"

NG3_EXISTS="false"
NG3_CREATED_DURING="false"
NG3_SIZE="0"

TXT_EXISTS="false"
YIELD_VALUE="0"

# Verify expected project file (.ng3)
if [ -f "$NG3_FILE" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$NG3_FILE" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$NG3_FILE" 2>/dev/null || echo "0")
    
    # Ensure it was created after the task started
    if [ "$NG3_MTIME" -gt "$TASK_START" ]; then
        NG3_CREATED_DURING="true"
    fi
fi

# Verify exported text file
if [ -f "$TXT_FILE" ]; then
    TXT_EXISTS="true"
    # Extract the first numeric sequence from the text file (basic regex parsing)
    RAW_VAL=$(cat "$TXT_FILE" | head -n 3 | tr -d '\r')
    YIELD_VALUE=$(echo "$RAW_VAL" | grep -oE '[0-9]+(\.[0-9]+)?' | head -n 1 || echo "0")
    if [ -z "$YIELD_VALUE" ]; then
        YIELD_VALUE="0"
    fi
fi

# Create structured JSON result representation
TEMP_JSON=$(mktemp)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING,
    "ng3_size_bytes": $NG3_SIZE,
    "txt_exists": $TXT_EXISTS,
    "yield_value": $YIELD_VALUE
}
EOF

# Safely move JSON result into a predictable, readable state for the verifier
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Result payload saved."
cat /tmp/task_result.json
echo "=== Export complete ==="