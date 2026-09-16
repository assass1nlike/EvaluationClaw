#!/bin/bash
echo "=== Exporting task results ==="

TASK_NAME="commercial_solar_canopy_optimization"
TARGET="/home/ga/Documents/Energy3D/phoenix_canopy.ng3"
START_TS=$(cat /tmp/${TASK_NAME}_start_time 2>/dev/null || echo "0")

# Capture final state screenshot
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || \
    DISPLAY=:1 import -window root /tmp/task_final.png 2>/dev/null || true

EXISTS="false"
CREATED_DURING_TASK="false"
MTIME="0"
SIZE="0"
HAS_PHOENIX="false"

if [ -f "$TARGET" ]; then
    EXISTS="true"
    MTIME=$(stat -c %Y "$TARGET" 2>/dev/null || echo "0")
    SIZE=$(stat -c %s "$TARGET" 2>/dev/null || echo "0")
    
    if [ "$MTIME" -gt "$START_TS" ]; then
        CREATED_DURING_TASK="true"
    fi
    
    # Energy3D files (.ng3) are Java serialized objects. 
    # The 'strings' command effectively checks for updated text fields like geographic location.
    if strings "$TARGET" | grep -qi "Phoenix"; then
        HAS_PHOENIX="true"
    fi
fi

# Determine if the application was running at the end
APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Create JSON output safely
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start_time": $START_TS,
    "app_running": $APP_RUNNING,
    "output_exists": $EXISTS,
    "created_during_task": $CREATED_DURING_TASK,
    "output_mtime": $MTIME,
    "output_size": $SIZE,
    "has_phoenix_string": $HAS_PHOENIX,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move to standard location securely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON saved:"
cat /tmp/task_result.json
echo "=== Export complete ==="