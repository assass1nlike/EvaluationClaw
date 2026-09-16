#!/bin/bash
echo "=== Exporting task results ==="

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
DIR="/home/ga/Documents/Energy3D"

# Take final evidence screenshot
source /workspace/scripts/task_utils.sh
take_screenshot /tmp/task_final.png

# Use Python to safely gather file stats and content without bash escaping issues
python3 << EOF
import os
import json

task_start = int("$TASK_START")
dir_path = "$DIR"

def get_file_info(filename):
    path = os.path.join(dir_path, filename)
    if os.path.exists(path):
        size = os.path.getsize(path)
        mtime = os.path.getmtime(path)
        return {
            "exists": True,
            "size": size,
            "created_during_task": mtime >= task_start
        }
    return {"exists": False, "size": 0, "created_during_task": False}

def get_file_content(filename, max_lines=5):
    path = os.path.join(dir_path, filename)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()[:max_lines]
                return "".join(lines).strip()
        except Exception:
            return ""
    return ""

result = {
    "flush_array": get_file_info("flush_array.ng3"),
    "tilted_array": get_file_info("tilted_array.ng3"),
    "flush_yield": get_file_info("flush_yield.txt"),
    "tilted_yield": get_file_info("tilted_yield.txt"),
    "recommendation": get_file_info("recommendation.txt"),
    "flush_yield_content": get_file_content("flush_yield.txt"),
    "tilted_yield_content": get_file_content("tilted_yield.txt"),
    "recommendation_content": get_file_content("recommendation.txt", max_lines=10)
}

# Write out cleanly
with open('/tmp/task_result.json', 'w') as f:
    json.dump(result, f, indent=2)
EOF

chmod 666 /tmp/task_result.json
echo "=== Export complete ==="