#!/bin/bash
echo "=== Exporting result ==="

source /workspace/scripts/task_utils.sh

# Capture the final state screenshot
take_screenshot /tmp/task_final.png

OUT_CSV="/home/ga/Documents/Energy3D/nairobi_yield.csv"
OUT_NG3="/home/ga/Documents/Energy3D/nairobi_microgrid.ng3"

TASK_START=$(cat /tmp/task_start_time 2>/dev/null || echo "0")
TASK_END=$(date +%s)

CSV_EXISTS="false"
CSV_SIZE="0"
CSV_CREATED_DURING_TASK="false"

NG3_EXISTS="false"
NG3_SIZE="0"
NG3_CREATED_DURING_TASK="false"

if [ -f "$OUT_CSV" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c %s "$OUT_CSV" 2>/dev/null || echo "0")
    CSV_MTIME=$(stat -c %Y "$OUT_CSV" 2>/dev/null || echo "0")
    if [ "$CSV_MTIME" -gt "$TASK_START" ]; then
        CSV_CREATED_DURING_TASK="true"
    fi
fi

if [ -f "$OUT_NG3" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c %s "$OUT_NG3" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c %Y "$OUT_NG3" 2>/dev/null || echo "0")
    if [ "$NG3_MTIME" -gt "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
fi

APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Create JSON file with temporary name to avoid permission issues
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "csv_exists": $CSV_EXISTS,
    "csv_size_bytes": $CSV_SIZE,
    "csv_created_during_task": $CSV_CREATED_DURING_TASK,
    "ng3_exists": $NG3_EXISTS,
    "ng3_size_bytes": $NG3_SIZE,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "app_was_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Make final result available
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json

echo "Result saved to /tmp/task_result.json"
echo "=== Export complete ==="