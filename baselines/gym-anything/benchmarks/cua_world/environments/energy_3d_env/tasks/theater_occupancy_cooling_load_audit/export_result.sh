#!/bin/bash
echo "=== Exporting task results ==="

source /workspace/scripts/task_utils.sh

# Record task end time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

REPORT_PATH="/home/ga/Documents/Energy3D/cooling_audit.txt"
NG3_PATH="/home/ga/Documents/Energy3D/occupied_theater.ng3"

# Take final screenshot
take_screenshot /tmp/task_final.png

# Check if application is running
APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Process state using Python to safely create JSON
python3 << PYEOF
import os
import json

task_start = int("$TASK_START")
report_path = "$REPORT_PATH"
ng3_path = "$NG3_PATH"

result = {
    "app_running": "$APP_RUNNING" == "true",
    "report_exists": False,
    "report_content": "",
    "report_created_during_task": False,
    "ng3_exists": False,
    "ng3_created_during_task": False,
    "ng3_has_miami_string": False
}

# Process the Report Text File
if os.path.exists(report_path):
    result["report_exists"] = True
    mtime = int(os.path.getmtime(report_path))
    result["report_created_during_task"] = mtime >= task_start
    
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            result["report_content"] = f.read()
    except Exception as e:
        result["report_content"] = f"Error reading report: {e}"

# Process the NG3 File
if os.path.exists(ng3_path):
    result["ng3_exists"] = True
    mtime = int(os.path.getmtime(ng3_path))
    result["ng3_created_during_task"] = mtime >= task_start
    
    # Try to peek into the binary/XML file to see if "Miami" or "400" was saved
    try:
        with open(ng3_path, 'rb') as f:
            content = f.read(100000) # Read up to 100kb
            if b'Miami' in content:
                result["ng3_has_miami_string"] = True
    except:
        pass

# Write JSON safely
with open("/tmp/task_result.json", "w", encoding='utf-8') as f:
    json.dump(result, f, indent=2)
PYEOF

# Fix permissions
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="