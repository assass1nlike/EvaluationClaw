#!/bin/bash
echo "=== Exporting perovskite_tandem_yield_simulation task results ==="

source /workspace/scripts/task_utils.sh

# Record task end time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

USER_DIR="/home/ga/Documents/Energy3D"
NEW_PROJ="$USER_DIR/high_efficiency_array.ng3"
GRAPH_IMG="$USER_DIR/yield_graph.png"
REPORT_TXT="$USER_DIR/yield_report.txt"

# Check if the new project was created during the task
PROJ_EXISTS="false"
PROJ_MODIFIED_DURING_TASK="false"
if [ -f "$NEW_PROJ" ]; then
    PROJ_EXISTS="true"
    PROJ_MTIME=$(stat -c %Y "$NEW_PROJ" 2>/dev/null || echo "0")
    if [ "$PROJ_MTIME" -gt "$TASK_START" ]; then
        PROJ_MODIFIED_DURING_TASK="true"
    fi
fi

# Check if the graph screenshot exists
GRAPH_EXISTS="false"
if [ -f "$GRAPH_IMG" ]; then
    GRAPH_EXISTS="true"
    GRAPH_MTIME=$(stat -c %Y "$GRAPH_IMG" 2>/dev/null || echo "0")
    if [ "$GRAPH_MTIME" -gt "$TASK_START" ]; then
        GRAPH_EXISTS="true" # It's a valid fresh export
    fi
fi

# Check the report text file
REPORT_EXISTS="false"
REPORT_CONTENT=""
if [ -f "$REPORT_TXT" ]; then
    REPORT_EXISTS="true"
    # Extract just the alphanumeric characters and basic punctuation to avoid JSON breakage
    REPORT_CONTENT=$(head -n 5 "$REPORT_TXT" | tr -cd '[:alnum:] .-\n' | tr '\n' ' ' | sed 's/"/\\"/g' || echo "")
fi

# Take final environment screenshot
take_screenshot /tmp/task_final.png

# Create JSON result (use temp file for permission safety)
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "project_exists": $PROJ_EXISTS,
    "project_modified_during_task": $PROJ_MODIFIED_DURING_TASK,
    "graph_exists": $GRAPH_EXISTS,
    "report_exists": $REPORT_EXISTS,
    "report_content": "$REPORT_CONTENT"
}
EOF

# Move to final location
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="