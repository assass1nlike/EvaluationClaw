#!/bin/bash
echo "=== Exporting task results ==="

source /workspace/scripts/task_utils.sh || true

# Take final screenshot as evidence
take_screenshot /tmp/task_final.png

# Extract file state and report contents into JSON via Python
python3 << 'EOF'
import os
import json
import time

# Safely read start time
start_time = 0
if os.path.exists('/tmp/task_start_time.txt'):
    try:
        with open('/tmp/task_start_time.txt', 'r') as f:
            start_time = int(f.read().strip())
    except Exception:
        pass

eco_path = "/home/ga/Documents/Energy3D/eco_building.ng3"
report_path = "/home/ga/Documents/Energy3D/thermostat_savings_report.txt"

result = {
    "task_start": start_time,
    "task_end": int(time.time()),
    "ng3_exists": os.path.exists(eco_path),
    "ng3_mtime": int(os.path.getmtime(eco_path)) if os.path.exists(eco_path) else 0,
    "ng3_size": os.path.getsize(eco_path) if os.path.exists(eco_path) else 0,
    "report_exists": os.path.exists(report_path),
    "report_mtime": int(os.path.getmtime(report_path)) if os.path.exists(report_path) else 0,
    "report_size": os.path.getsize(report_path) if os.path.exists(report_path) else 0,
    "report_content": ""
}

# Safely extract text report content
if result["report_exists"]:
    try:
        with open(report_path, 'r', encoding='utf-8', errors='ignore') as f:
            result["report_content"] = f.read()[:5000]  # Cap length for safety
    except Exception as e:
        result["report_content"] = f"Error reading file: {e}"

# Write to tmp location for verifier
with open('/tmp/task_result.json', 'w') as f:
    json.dump(result, f)
EOF

# Ensure permissions
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true

echo "Export completed. Result saved to /tmp/task_result.json."