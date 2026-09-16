#!/bin/bash
echo "=== Exporting remote_clinic_netzero_design task results ==="

# Source utilities
source /workspace/scripts/task_utils.sh

# Take final screenshot
take_screenshot /tmp/task_final.png

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
NG3_PATH="/home/ga/Documents/Energy3D/phoenix_clinic.ng3"
CSV_PATH="/home/ga/Documents/Energy3D/phoenix_clinic_energy.csv"

# Use python to generate robust JSON output of file stats
python3 << EOF > /tmp/task_result.json
import os
import json

task_start = int("$TASK_START")
ng3_path = "$NG3_PATH"
csv_path = "$CSV_PATH"

def check_file(path):
    if os.path.exists(path):
        mtime = int(os.path.getmtime(path))
        return {
            "exists": True,
            "created_during_task": mtime >= task_start,
            "size_bytes": os.path.getsize(path),
            "mtime": mtime
        }
    return {"exists": False, "created_during_task": False, "size_bytes": 0, "mtime": 0}

result = {
    "task_start": task_start,
    "ng3_file": check_file(ng3_path),
    "csv_file": check_file(csv_path),
    "screenshot_exists": os.path.exists("/tmp/task_final.png")
}

with open("/tmp/task_result.json", "w") as f:
    json.dump(result, f, indent=2)
EOF

chmod 666 /tmp/task_result.json 2>/dev/null || true

echo "Export completed. Results saved to /tmp/task_result.json"
cat /tmp/task_result.json