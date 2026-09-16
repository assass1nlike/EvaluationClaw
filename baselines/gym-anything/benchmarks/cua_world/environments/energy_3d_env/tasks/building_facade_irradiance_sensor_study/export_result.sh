#!/bin/bash
echo "=== Exporting task results ==="

source /workspace/scripts/task_utils.sh

# Take final screenshot of the UI state
take_screenshot /tmp/task_final.png

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
USER_DIR="/home/ga/Documents/Energy3D"
TARGET_MODEL="$USER_DIR/facade_sensors.ng3"
TARGET_GRAPH="$USER_DIR/sensor_graph.png"

# 1. Analyze Model File (.ng3)
MODEL_EXISTS="false"
MODEL_CREATED_DURING_TASK="false"
MODEL_SIZE="0"
SENSOR_HINTS="0"

if [ -f "$TARGET_MODEL" ]; then
    MODEL_EXISTS="true"
    MODEL_SIZE=$(stat -c %s "$TARGET_MODEL" 2>/dev/null || echo "0")
    MODEL_MTIME=$(stat -c %Y "$TARGET_MODEL" 2>/dev/null || echo "0")
    
    if [ "$MODEL_MTIME" -ge "$TASK_START" ]; then
        MODEL_CREATED_DURING_TASK="true"
    fi

    # Energy3D saves as Java Serialized or JSON. 'strings' is a safe cross-format way to sniff for objects.
    SENSOR_HINTS=$(strings "$TARGET_MODEL" 2>/dev/null | grep -i -E "sensor|LightSensor" | wc -l)
fi

# 2. Analyze Graph Screenshot (.png)
GRAPH_EXISTS="false"
GRAPH_CREATED_DURING_TASK="false"
GRAPH_SIZE="0"

if [ -f "$TARGET_GRAPH" ]; then
    GRAPH_EXISTS="true"
    GRAPH_SIZE=$(stat -c %s "$TARGET_GRAPH" 2>/dev/null || echo "0")
    GRAPH_MTIME=$(stat -c %Y "$TARGET_GRAPH" 2>/dev/null || echo "0")
    
    if [ "$GRAPH_MTIME" -ge "$TASK_START" ]; then
        GRAPH_CREATED_DURING_TASK="true"
    fi
fi

# Determine if app was running
APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Create JSON payload
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "app_was_running": $APP_RUNNING,
    "model_exists": $MODEL_EXISTS,
    "model_created_during_task": $MODEL_CREATED_DURING_TASK,
    "model_size_bytes": $MODEL_SIZE,
    "sensor_strings_found": $SENSOR_HINTS,
    "graph_exists": $GRAPH_EXISTS,
    "graph_created_during_task": $GRAPH_CREATED_DURING_TASK,
    "graph_size_bytes": $GRAPH_SIZE,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move securely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result JSON saved to /tmp/task_result.json:"
cat /tmp/task_result.json

echo "=== Export complete ==="