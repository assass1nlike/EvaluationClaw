#!/bin/bash
echo "=== Exporting greenhouse_analysis result ==="

source /workspace/scripts/task_utils.sh || true

# Take final verification screenshot of the entire desktop
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || \
    DISPLAY=:1 import -window root /tmp/task_final.png 2>/dev/null || true

START_TS=$(cat /tmp/greenhouse_analysis_start_ts 2>/dev/null || echo "0")
DESIGN_FILE="/home/ga/Documents/Energy3D/greenhouse_design.ng3"
SCREENSHOT_FILE="/home/ga/Documents/Energy3D/winter_radiation_map.png"

# Check if the expected design file was saved
DESIGN_EXISTS="false"
DESIGN_CREATED_DURING_TASK="false"
if [ -f "$DESIGN_FILE" ]; then
    DESIGN_EXISTS="true"
    MTIME=$(stat -c %Y "$DESIGN_FILE" 2>/dev/null || echo "0")
    if [ "$MTIME" -ge "$START_TS" ]; then
        DESIGN_CREATED_DURING_TASK="true"
    fi
fi

# Check if the required agent screenshot artifact was saved
SCREENSHOT_EXISTS="false"
SCREENSHOT_CREATED_DURING_TASK="false"
if [ -f "$SCREENSHOT_FILE" ]; then
    SCREENSHOT_EXISTS="true"
    MTIME=$(stat -c %Y "$SCREENSHOT_FILE" 2>/dev/null || echo "0")
    if [ "$MTIME" -ge "$START_TS" ]; then
        SCREENSHOT_CREATED_DURING_TASK="true"
    fi
fi

# Programmatic check backup: Since .ng3 is Java serialized binary,
# we can use 'strings' to perform a rudimentary check for the location
HAS_DENVER_STRING="false"
if [ "$DESIGN_EXISTS" = "true" ]; then
    if strings "$DESIGN_FILE" | grep -qi "Denver"; then
        HAS_DENVER_STRING="true"
    fi
fi

# Generate JSON payload for the Python verifier
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $START_TS,
    "design_exists": $DESIGN_EXISTS,
    "design_created_during_task": $DESIGN_CREATED_DURING_TASK,
    "screenshot_exists": $SCREENSHOT_EXISTS,
    "screenshot_created_during_task": $SCREENSHOT_CREATED_DURING_TASK,
    "has_denver_string": $HAS_DENVER_STRING,
    "timestamp": "$(date -Iseconds)"
}
EOF

# Move payload safely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="