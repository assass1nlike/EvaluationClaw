#!/bin/bash
echo "=== Exporting Tree Shading Impact results ==="

source /workspace/scripts/task_utils.sh || true

# Take final screenshot
take_screenshot /tmp/task_final.png

# Create a JSON payload with file existence, sizes, and timestamps
python3 << 'PYEOF'
import json
import os

start_time = 0
try:
    with open('/tmp/task_start_time.txt', 'r') as f:
        start_time = int(f.read().strip())
except Exception:
    pass

def get_file_info(path):
    if not os.path.exists(path):
        return {"exists": False, "created_during_task": False, "size": 0}
    mtime = os.path.getmtime(path)
    return {
        "exists": True,
        "size": os.path.getsize(path),
        "mtime": mtime,
        "created_during_task": mtime > start_time
    }

res = {
    "csv1": get_file_info("/home/ga/Documents/Energy3D/yield_current.csv"),
    "csv2": get_file_info("/home/ga/Documents/Energy3D/yield_year_20.csv"),
    "ng3": get_file_info("/home/ga/Documents/Energy3D/tree_shading_study.ng3"),
    "app_running": os.system("pgrep -f org.concord.energy3d.MainApplication > /dev/null") == 0
}

with open("/tmp/task_result.json", "w") as f:
    json.dump(res, f)
PYEOF

# Ensure permissions
chmod 666 /tmp/task_result.json 2>/dev/null || true

echo "Export metadata saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="