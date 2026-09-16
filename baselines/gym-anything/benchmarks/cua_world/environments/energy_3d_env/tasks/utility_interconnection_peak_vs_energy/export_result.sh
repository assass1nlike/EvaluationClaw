#!/bin/bash
echo "=== Exporting utility_interconnection_peak_vs_energy result ==="

# Define file paths
OUTPUT_FILE="/home/ga/Documents/Energy3D/interconnection_report.txt"
START_TS_FILE="/tmp/task_start_time.txt"
RESULT_JSON="/tmp/task_result.json"

# Take final screenshot
echo "Capturing final state screenshot..."
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || \
    DISPLAY=:1 import -window root /tmp/task_final.png 2>/dev/null || true

# Determine if the application is still running
APP_RUNNING="false"
if pgrep -f "org.concord.energy3d.MainApplication" > /dev/null; then
    APP_RUNNING="true"
fi

# Use Python to safely package file contents and metadata into JSON
python3 << EOF
import os
import json
import time

start_ts_file = "${START_TS_FILE}"
output_file = "${OUTPUT_FILE}"
result_json = "${RESULT_JSON}"
app_running = ${APP_RUNNING}

start_ts = 0
if os.path.exists(start_ts_file):
    try:
        with open(start_ts_file, 'r') as f:
            start_ts = int(f.read().strip())
    except:
        pass

output_exists = os.path.exists(output_file)
file_created_during_task = False
content = ""

if output_exists:
    mtime = os.path.getmtime(output_file)
    if mtime >= start_ts:
        file_created_during_task = True
    
    try:
        with open(output_file, 'r') as f:
            content = f.read()
    except Exception as e:
        content = f"Error reading file: {e}"

result = {
    "task_start_ts": start_ts,
    "export_ts": int(time.time()),
    "app_running": app_running,
    "output_exists": output_exists,
    "file_created_during_task": file_created_during_task,
    "content": content
}

with open(result_json, 'w') as f:
    json.dump(result, f, indent=2)
EOF

# Fix permissions so the verifier can easily read it
chmod 666 "$RESULT_JSON" 2>/dev/null || true

echo "Result saved to $RESULT_JSON"
cat "$RESULT_JSON"
echo "=== Export complete ==="