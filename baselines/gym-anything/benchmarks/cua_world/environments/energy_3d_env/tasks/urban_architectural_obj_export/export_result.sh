#!/bin/bash
echo "=== Exporting urban_architectural_obj_export result ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

# Record task end time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

# Take final screenshot
take_screenshot /tmp/task_final.png ga

START_DIR="/home/ga/Documents/Energy3D"
EXPECTED_OBJ="${START_DIR}/proposed_city_block.obj"
EXPECTED_NG3="${START_DIR}/proposed_city_block.ng3"

# Check OBJ Output
OBJ_EXISTS="false"
OBJ_CREATED_DURING_TASK="false"
OBJ_SIZE="0"
OBJ_VERTICES="0"
OBJ_FACES="0"

if [ -f "$EXPECTED_OBJ" ]; then
    OBJ_EXISTS="true"
    OBJ_SIZE=$(stat -c %s "$EXPECTED_OBJ" 2>/dev/null || echo "0")
    OBJ_MTIME=$(stat -c %Y "$EXPECTED_OBJ" 2>/dev/null || echo "0")
    
    if [ "$OBJ_MTIME" -ge "$TASK_START" ]; then
        OBJ_CREATED_DURING_TASK="true"
    fi
    
    # Analyze OBJ content
    OBJ_VERTICES=$(grep -c "^v " "$EXPECTED_OBJ" 2>/dev/null || echo "0")
    OBJ_FACES=$(grep -c "^f " "$EXPECTED_OBJ" 2>/dev/null || echo "0")
fi

# Check NG3 Output
NG3_EXISTS="false"
NG3_CREATED_DURING_TASK="false"
NG3_SIZE="0"

if [ -f "$EXPECTED_NG3" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$EXPECTED_NG3" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$EXPECTED_NG3" 2>/dev/null || echo "0")
    
    if [ "$NG3_MTIME" -ge "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
fi

# Check if application is running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Generate Result JSON
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "obj_exists": $OBJ_EXISTS,
    "obj_created_during_task": $OBJ_CREATED_DURING_TASK,
    "obj_size_bytes": $OBJ_SIZE,
    "obj_vertices": $OBJ_VERTICES,
    "obj_faces": $OBJ_FACES,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "ng3_size_bytes": $NG3_SIZE,
    "app_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move to final location securely
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="