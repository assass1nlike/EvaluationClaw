#!/bin/bash
echo "=== Exporting task results ==="

source /workspace/scripts/task_utils.sh || true

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
TARGET_NG3="/home/ga/Documents/Energy3D/city-block-heliostat.ng3"
TARGET_PNG="/home/ga/Documents/Energy3D/heliostat_rays.png"

# Take a final system screenshot for backup
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || true

# 1. Check if the saved .ng3 file exists and was modified during task
NG3_EXISTS="false"
NG3_CREATED_DURING_TASK="false"
NG3_SIZE="0"

if [ -f "$TARGET_NG3" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$TARGET_NG3" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$TARGET_NG3" 2>/dev/null || echo "0")
    
    if [ "$NG3_MTIME" -gt "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
fi

# 2. Check if the requested screenshot was saved
PNG_EXISTS="false"
PNG_SIZE="0"

if [ -f "$TARGET_PNG" ]; then
    PNG_EXISTS="true"
    PNG_SIZE=$(stat -c %s "$TARGET_PNG" 2>/dev/null || echo "0")
fi

# Create export JSON
TEMP_JSON=$(mktemp)
cat > "$TEMP_JSON" << EOF
{
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "ng3_size_bytes": $NG3_SIZE,
    "png_exists": $PNG_EXISTS,
    "png_size_bytes": $PNG_SIZE,
    "timestamp": "$(date -Iseconds)"
}
EOF

# Move to standard location
rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Exported results to /tmp/task_result.json:"
cat /tmp/task_result.json
echo "=== Export complete ==="