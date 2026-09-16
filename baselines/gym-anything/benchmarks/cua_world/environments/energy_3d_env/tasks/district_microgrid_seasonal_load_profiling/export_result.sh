#!/bin/bash
# Export script for district microgrid profiling task
echo "=== Exporting district microgrid profiling results ==="

source /workspace/scripts/task_utils.sh || { echo "Failed to source task_utils"; exit 1; }

TASK_NAME="district_microgrid_seasonal_load_profiling"
START_TS=$(cat "/tmp/${TASK_NAME}_start_ts" 2>/dev/null || echo "0")
DOC_DIR="/home/ga/Documents/Energy3D"

# Target files
TARGET_PROJECT="$DOC_DIR/houston_microgrid_district.ng3"
TARGET_AUG_CSV="$DOC_DIR/houston_microgrid_august.csv"
TARGET_JAN_CSV="$DOC_DIR/houston_microgrid_january.csv"

# Capture final screenshot
take_screenshot /tmp/task_final.png ga

# Check for modified project file
PROJECT_EXISTS="false"
PROJECT_SIZE=0
PROJECT_MTIME=0
LOCATION_SET="false"

if [ -f "$TARGET_PROJECT" ]; then
    PROJECT_EXISTS="true"
    PROJECT_SIZE=$(stat -c%s "$TARGET_PROJECT" 2>/dev/null || echo "0")
    PROJECT_MTIME=$(stat -c%Y "$TARGET_PROJECT" 2>/dev/null || echo "0")
    
    # Energy3D saves in a Java serialized object format, but plain text strings are visible.
    # We grep the strings for "Houston, TX" to verify they updated the location.
    if strings "$TARGET_PROJECT" 2>/dev/null | grep -iq "Houston, TX"; then
        LOCATION_SET="true"
    fi
fi

# Check for August CSV
AUG_CSV_EXISTS="false"
AUG_CSV_SIZE=0
AUG_CSV_LINES=0

if [ -f "$TARGET_AUG_CSV" ]; then
    AUG_CSV_EXISTS="true"
    AUG_CSV_SIZE=$(stat -c%s "$TARGET_AUG_CSV" 2>/dev/null || echo "0")
    AUG_CSV_LINES=$(wc -l < "$TARGET_AUG_CSV" 2>/dev/null || echo "0")
    # Copy to tmp so the verifier can easily fetch it
    cp "$TARGET_AUG_CSV" "/tmp/houston_microgrid_august.csv" 2>/dev/null || true
    chmod 666 "/tmp/houston_microgrid_august.csv" 2>/dev/null || true
fi

# Check for January CSV
JAN_CSV_EXISTS="false"
JAN_CSV_SIZE=0
JAN_CSV_LINES=0

if [ -f "$TARGET_JAN_CSV" ]; then
    JAN_CSV_EXISTS="true"
    JAN_CSV_SIZE=$(stat -c%s "$TARGET_JAN_CSV" 2>/dev/null || echo "0")
    JAN_CSV_LINES=$(wc -l < "$TARGET_JAN_CSV" 2>/dev/null || echo "0")
    # Copy to tmp so the verifier can easily fetch it
    cp "$TARGET_JAN_CSV" "/tmp/houston_microgrid_january.csv" 2>/dev/null || true
    chmod 666 "/tmp/houston_microgrid_january.csv" 2>/dev/null || true
fi

# Check if application is still running
APP_RUNNING=$(pgrep -f "org.concord.energy3d.MainApplication" > /dev/null && echo "true" || echo "false")

# Build JSON Result File
TEMP_JSON=$(mktemp /tmp/result.XXXXXX.json)
cat > "$TEMP_JSON" << EOF
{
    "task_start_timestamp": $START_TS,
    "app_running": $APP_RUNNING,
    "project_file": {
        "exists": $PROJECT_EXISTS,
        "size_bytes": $PROJECT_SIZE,
        "mtime": $PROJECT_MTIME,
        "location_houston_found": $LOCATION_SET
    },
    "august_csv": {
        "exists": $AUG_CSV_EXISTS,
        "size_bytes": $AUG_CSV_SIZE,
        "lines": $AUG_CSV_LINES
    },
    "january_csv": {
        "exists": $JAN_CSV_EXISTS,
        "size_bytes": $JAN_CSV_SIZE,
        "lines": $JAN_CSV_LINES
    }
}
EOF

# Move JSON to final location
rm -f /tmp/task_result.json 2>/dev/null || sudo rm -f /tmp/task_result.json 2>/dev/null || true
cp "$TEMP_JSON" /tmp/task_result.json 2>/dev/null || sudo cp "$TEMP_JSON" /tmp/task_result.json
chmod 666 /tmp/task_result.json 2>/dev/null || sudo chmod 666 /tmp/task_result.json 2>/dev/null || true
rm -f "$TEMP_JSON"

echo "Result saved to /tmp/task_result.json"
cat /tmp/task_result.json
echo "=== Export complete ==="