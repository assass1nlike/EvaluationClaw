#!/bin/bash
echo "=== Exporting residential_window_retrofit_analysis result ==="

source /workspace/scripts/task_utils.sh || true

# Take the final system screenshot
take_screenshot /tmp/task_final.png

# Use Python to safely collect all artifact statuses and build the JSON result
python3 << 'PYEOF'
import json
import os
import glob
import time

result = {}

# Record time limits for anti-gaming checks
try:
    with open("/tmp/task_start_time.txt", "r") as f:
        result["task_start_time"] = int(f.read().strip())
except Exception:
    result["task_start_time"] = 0

result["task_end_time"] = int(time.time())

# Artifact Paths
ng3_path = "/home/ga/Documents/Energy3D/window_retrofit.ng3"
report_path = "/home/ga/Documents/Energy3D/retrofit_report.txt"
png_path = "/home/ga/Documents/Energy3D/upgraded_analysis.png"

# Fallback path finding in case of slight typos
if not os.path.exists(report_path):
    reports = glob.glob("/home/ga/Documents/Energy3D/*report*.txt")
    if reports: report_path = reports[0]

if not os.path.exists(png_path):
    pngs = glob.glob("/home/ga/Documents/Energy3D/*analysis*.png")
    if pngs: png_path = pngs[0]

if not os.path.exists(ng3_path):
    ng3s = glob.glob("/home/ga/Documents/Energy3D/*retrofit*.ng3")
    if ng3s: ng3_path = ng3s[0]

# Extract Model Data
result["ng3_exists"] = os.path.exists(ng3_path)
if result["ng3_exists"]:
    result["ng3_size"] = os.path.getsize(ng3_path)
    result["ng3_mtime"] = os.path.getmtime(ng3_path)
    result["ng3_created_during_task"] = result["ng3_mtime"] >= result["task_start_time"]

# Extract Report Content safely
result["report_exists"] = os.path.exists(report_path)
if result["report_exists"]:
    with open(report_path, "r", errors="ignore") as f:
        result["report_content"] = f.read()

# Extract PNG info
result["png_exists"] = os.path.exists(png_path)
result["png_path_container"] = png_path if result["png_exists"] else ""
if result["png_exists"]:
    result["png_mtime"] = os.path.getmtime(png_path)
    result["png_created_during_task"] = result["png_mtime"] >= result["task_start_time"]

# App State
result["app_running"] = os.system("pgrep -f 'Energy3D' > /dev/null") == 0

with open("/tmp/task_result.json", "w") as f:
    json.dump(result, f, indent=2)
PYEOF

chmod 666 /tmp/task_result.json 2>/dev/null || true

echo "Exported Result:"
cat /tmp/task_result.json
echo "=== Export complete ==="