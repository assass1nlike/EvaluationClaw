#!/bin/bash
echo "=== Exporting utility_scale_solar_tracker_upgrade result ==="

source /workspace/scripts/task_utils.sh || true

TASK_NAME="utility_scale_solar_tracker_upgrade"
START_TS=$(cat /tmp/${TASK_NAME}_start_ts 2>/dev/null || echo "0")
TARGET_FILE="/home/ga/Documents/Energy3D/phoenix_hsat_array.ng3"
TEMP_NG3="/tmp/agent_output.ng3"

# Capture final screenshot
take_screenshot /tmp/task_final.png ga

EXISTS="false"
MTIME="0"
SIZE="0"

if [ -f "$TARGET_FILE" ]; then
    EXISTS="true"
    MTIME=$(stat -c %Y "$TARGET_FILE" 2>/dev/null || echo "0")
    SIZE=$(stat -c %s "$TARGET_FILE" 2>/dev/null || echo "0")
    
    # Copy file to a neutral tmp location for the verifier to copy_from_env
    rm -f "$TEMP_NG3" 2>/dev/null || sudo rm -f "$TEMP_NG3" 2>/dev/null || true
    cp "$TARGET_FILE" "$TEMP_NG3" 2>/dev/null || sudo cp "$TARGET_FILE" "$TEMP_NG3"
    chmod 666 "$TEMP_NG3" 2>/dev/null || sudo chmod 666 "$TEMP_NG3" 2>/dev/null || true
fi

TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start_time": $START_TS,
    "file_exists": $EXISTS,
    "file_mtime": $MTIME,
    "file_size": $SIZE
}
EOF

rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON saved to /tmp/task_result.json"
cat /tmp/task_result.json

echo "=== Export complete ==="