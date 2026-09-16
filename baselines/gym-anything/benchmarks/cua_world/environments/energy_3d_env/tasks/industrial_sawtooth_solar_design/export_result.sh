#!/bin/bash
echo "=== Exporting task results ==="

# Record task end time and start time
TASK_END=$(date +%s)
TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

NG3_PATH="/home/ga/Documents/Energy3D/factory_sawtooth_solar.ng3"
CSV_PATH="/home/ga/Documents/Energy3D/factory_annual_energy.csv"

# Take final screenshot
DISPLAY=:1 scrot /tmp/task_final.png 2>/dev/null || true

# 1. Check NG3 Project File
NG3_EXISTS="false"
NG3_CREATED_DURING_TASK="false"
DETROIT_IN_NG3="false"

if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$NG3_PATH" 2>/dev/null || echo "0")
    
    if [ "$NG3_MTIME" -gt "$TASK_START" ]; then
        NG3_CREATED_DURING_TASK="true"
    fi
    
    # Energy3D stores projects as binary serialized Java data or JSON depending on version.
    # We can use strings to grep for location metadata inside the blob.
    if strings "$NG3_PATH" | grep -qi "Detroit"; then
        DETROIT_IN_NG3="true"
    fi
fi

# 2. Check exported CSV Analysis File
CSV_EXISTS="false"
CSV_CREATED_DURING_TASK="false"

if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    CSV_MTIME=$(stat -c %Y "$CSV_PATH" 2>/dev/null || echo "0")
    
    if [ "$CSV_MTIME" -gt "$TASK_START" ]; then
        CSV_CREATED_DURING_TASK="true"
    fi
fi

# 3. Parse CSV data securely using Python
python3 - << 'EOF' > /tmp/csv_stats.json
import os
import csv
import json

csv_path = "/home/ga/Documents/Energy3D/factory_annual_energy.csv"
stats = {"rows": 0, "solar_sum": 0.0}

if os.path.exists(csv_path):
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, [])
            solar_idx = -1
            
            # Find the solar generation column
            for i, col in enumerate(header):
                if 'solar' in col.lower() or 'pv' in col.lower():
                    solar_idx = i
                    break
            
            rows = 0
            solar_sum = 0.0
            
            for row in reader:
                if not row or not row[0].strip():
                    continue
                # Skip 'Total' summary row
                if 'total' in row[0].lower():
                    continue
                    
                rows += 1
                if solar_idx != -1 and solar_idx < len(row):
                    try:
                        val = float(row[solar_idx].replace(',', ''))
                        solar_sum += val
                    except ValueError:
                        pass
                        
            stats["rows"] = rows
            stats["solar_sum"] = solar_sum
    except Exception as e:
        pass

with open("/tmp/csv_stats.json", "w") as f:
    json.dump(stats, f)
EOF

CSV_ROWS=$(python3 -c 'import json; print(json.load(open("/tmp/csv_stats.json")).get("rows", 0))' 2>/dev/null || echo "0")
CSV_SOLAR_SUM=$(python3 -c 'import json; print(json.load(open("/tmp/csv_stats.json")).get("solar_sum", 0.0))' 2>/dev/null || echo "0.0")

# 4. Check if app is running
APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# 5. Build Result JSON
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "task_end": $TASK_END,
    "ng3_exists": $NG3_EXISTS,
    "ng3_created_during_task": $NG3_CREATED_DURING_TASK,
    "detroit_in_ng3": $DETROIT_IN_NG3,
    "csv_exists": $CSV_EXISTS,
    "csv_created_during_task": $CSV_CREATED_DURING_TASK,
    "csv_rows": $CSV_ROWS,
    "csv_solar_sum": $CSV_SOLAR_SUM,
    "app_was_running": $APP_RUNNING,
    "screenshot_path": "/tmp/task_final.png"
}
EOF

# Move to final destination
rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON" /tmp/csv_stats.json

echo "Export complete. Result saved to /tmp/task_result.json."
cat /tmp/task_result.json