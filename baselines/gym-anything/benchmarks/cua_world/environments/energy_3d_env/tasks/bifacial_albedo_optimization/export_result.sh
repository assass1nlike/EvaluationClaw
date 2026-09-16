#!/bin/bash
echo "=== Exporting bifacial_albedo_optimization result ==="

source /workspace/scripts/task_utils.sh

TASK_START=$(cat /tmp/task_start_time.txt 2>/dev/null || echo "0")

# Capture final screenshot for evidence
take_screenshot /tmp/task_final.png

NG3_PATH="/home/ga/Documents/Energy3D/bifacial_optimized.ng3"
CSV_PATH="/home/ga/Documents/Energy3D/bifacial_yield.csv"

# Capture state of generated .ng3 project file
NG3_EXISTS="false"
NG3_SIZE="0"
NG3_MTIME="0"
if [ -f "$NG3_PATH" ]; then
    NG3_EXISTS="true"
    NG3_SIZE=$(stat -c%s "$NG3_PATH" 2>/dev/null || echo "0")
    NG3_MTIME=$(stat -c%Y "$NG3_PATH" 2>/dev/null || echo "0")
fi

# Capture state of exported .csv yield file
CSV_EXISTS="false"
CSV_SIZE="0"
CSV_MTIME="0"
if [ -f "$CSV_PATH" ]; then
    CSV_EXISTS="true"
    CSV_SIZE=$(stat -c%s "$CSV_PATH" 2>/dev/null || echo "0")
    CSV_MTIME=$(stat -c%Y "$CSV_PATH" 2>/dev/null || echo "0")
fi

# Do basic string search on the binary/XML .ng3 file
NG3_HAS_BIFACIAL="false"
NG3_HAS_ALBEDO="false"
if [ "$NG3_EXISTS" = "true" ]; then
    if grep -a -i -q "bifacial" "$NG3_PATH" 2>/dev/null; then
        NG3_HAS_BIFACIAL="true"
    fi
    if grep -a -i -q "albedo" "$NG3_PATH" 2>/dev/null; then
        NG3_HAS_ALBEDO="true"
    fi
fi

TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start": $TASK_START,
    "ng3_exists": $NG3_EXISTS,
    "ng3_size": $NG3_SIZE,
    "ng3_mtime": $NG3_MTIME,
    "csv_exists": $CSV_EXISTS,
    "csv_size": $CSV_SIZE,
    "csv_mtime": $CSV_MTIME,
    "ng3_has_bifacial": $NG3_HAS_BIFACIAL,
    "ng3_has_albedo": $NG3_HAS_ALBEDO
}
EOF

rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "=== Export complete ==="