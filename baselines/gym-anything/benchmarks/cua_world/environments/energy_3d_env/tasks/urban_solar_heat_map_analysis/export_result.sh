#!/bin/bash
echo "=== Exporting urban_solar_heat_map_analysis result ==="

# Get task start time
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
USER_DIR="/home/ga/Documents/Energy3D"
TARGET_PROJ="$USER_DIR/city-block-boston-summer.ng3"
TARGET_IMG="$USER_DIR/boston_summer_heatmap.png"

# 1. Check Project File
PROJ_EXISTS="false"
PROJ_CREATED="false"
PROJ_SIZE="0"
if [ -f "$TARGET_PROJ" ]; then
    PROJ_EXISTS="true"
    PROJ_SIZE=$(stat -c %s "$TARGET_PROJ" 2>/dev/null || echo "0")
    PROJ_MTIME=$(stat -c %Y "$TARGET_PROJ" 2>/dev/null || echo "0")
    
    # Verify file was created AFTER task started
    if [ "$PROJ_MTIME" -ge "$TASK_START" ]; then
        PROJ_CREATED="true"
    fi
fi

# 2. Check Screenshot File
IMG_EXISTS="false"
IMG_CREATED="false"
IMG_SIZE="0"
if [ -f "$TARGET_IMG" ]; then
    IMG_EXISTS="true"
    IMG_SIZE=$(stat -c %s "$TARGET_IMG" 2>/dev/null || echo "0")
    IMG_MTIME=$(stat -c %Y "$TARGET_IMG" 2>/dev/null || echo "0")
    
    # Verify image was created AFTER task started
    if [ "$IMG_MTIME" -ge "$TASK_START" ]; then
        IMG_CREATED="true"
    fi
fi

# 3. Check App State
APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Take final evidence screenshot for additional debugging
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || true

# Export variables to JSON
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "proj_exists": $PROJ_EXISTS,
    "proj_created_during_task": $PROJ_CREATED,
    "proj_size": $PROJ_SIZE,
    "img_exists": $IMG_EXISTS,
    "img_created_during_task": $IMG_CREATED,
    "img_size": $IMG_SIZE,
    "app_running": $APP_RUNNING
}
EOF

# Move securely
mv "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json

echo "=== Export complete ==="
cat /tmp/task_result.json