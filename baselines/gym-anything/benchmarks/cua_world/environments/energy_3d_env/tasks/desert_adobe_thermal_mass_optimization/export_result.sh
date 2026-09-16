#!/bin/bash
echo "=== Exporting desert_adobe_thermal_mass_optimization result ==="

# Source utilities
source /workspace/scripts/task_utils.sh

# Take final screenshot for VLM
take_screenshot /tmp/task_final.png

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")
DST_DIR="/home/ga/Documents/Energy3D"

# Helper function to check CSV validity
check_csv() {
    local file=$1
    if [ -f "$file" ]; then
        mtime=$(stat -c %Y "$file" 2>/dev/null || echo "0")
        size=$(stat -c %s "$file" 2>/dev/null || echo "0")
        header=$(head -n 1 "$file" 2>/dev/null | tr -d '\r')
        is_valid="false"
        
        # Energy3D CSVs contain "Time" as the first column
        if echo "$header" | grep -qi "Time"; then
            is_valid="true"
        fi
        echo "{\"exists\": true, \"mtime\": $mtime, \"size\": $size, \"valid_header\": $is_valid}"
    else
        echo "{\"exists\": false, \"mtime\": 0, \"size\": 0, \"valid_header\": false}"
    fi
}

BASELINE_JSON=$(check_csv "$DST_DIR/baseline_wood_frame.csv")
ADOBE_JSON=$(check_csv "$DST_DIR/adobe_thermal_mass.csv")

# Check if the modified .ng3 model was saved
if [ -f "$DST_DIR/adobe_house_design.ng3" ]; then
    NG3_EXISTS="true"
    NG3_MTIME=$(stat -c %Y "$DST_DIR/adobe_house_design.ng3" 2>/dev/null || echo "0")
else
    NG3_EXISTS="false"
    NG3_MTIME="0"
fi

# Package everything into a JSON file for the python verifier
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "baseline_csv": $BASELINE_JSON,
    "adobe_csv": $ADOBE_JSON,
    "ng3_exists": $NG3_EXISTS,
    "ng3_mtime": $NG3_MTIME
}
EOF

# Move securely with permissions
rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json
rm -f "$TEMP_JSON"

echo "Export completed. Result payload:"
cat /tmp/task_result.json