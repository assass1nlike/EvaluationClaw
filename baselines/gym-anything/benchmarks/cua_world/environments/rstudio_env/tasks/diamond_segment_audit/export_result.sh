#!/bin/bash
echo "=== Exporting Diamond Segment Audit Result ==="

# pre_task ran as root, so stale temp files may be root-owned.
rm -f /tmp/diamond_segment_audit_result.json 2>/dev/null || sudo rm -f /tmp/diamond_segment_audit_result.json 2>/dev/null || true

TASK_START=$(cat /tmp/diamond_segment_audit_start_ts 2>/dev/null || echo "0")

DISPLAY=:1 import -window root /tmp/diamond_segment_audit_end_screenshot.png 2>/dev/null || \
    DISPLAY=:1 scrot /tmp/diamond_segment_audit_end_screenshot.png 2>/dev/null || true

OUT=/home/ga/RProjects/output
python3 << 'PYEOF' > /tmp/diamond_segment_audit_result.json 2>/tmp/diamond_segment_audit_export.err
import csv, json, os

OUT = "/home/ga/RProjects/output"
TASK_START = 0
try:
    TASK_START = int(open("/tmp/diamond_segment_audit_start_ts").read().strip())
except Exception:
    pass


def stat(path):
    if not os.path.isfile(path):
        return {"exists": False, "is_new": False, "size_bytes": 0}
    return {
        "exists": True,
        "is_new": int(os.path.getmtime(path)) > TASK_START,
        "size_bytes": os.path.getsize(path),
    }


def read_csv(path):
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception:
        return None


report_path = os.path.join(OUT, "segment_report.csv")
excluded_path = os.path.join(OUT, "excluded_records.csv")
summary_path = os.path.join(OUT, "audit_summary.json")
plot_path = os.path.join(OUT, "price_per_carat_by_segment.png")

report_rows = read_csv(report_path)
report_cols = list(report_rows[0].keys()) if report_rows else []
excluded_rows = read_csv(excluded_path)
excluded_cols = list(excluded_rows[0].keys()) if excluded_rows else []

summary = None
summary_error = ""
try:
    with open(summary_path, encoding="utf-8-sig") as f:
        summary = json.load(f)
except Exception as e:
    summary_error = str(e)

plot = stat(plot_path)
is_png = False
if plot["exists"]:
    try:
        with open(plot_path, "rb") as f:
            is_png = f.read(8) == b"\x89PNG\r\n\x1a\n"
    except Exception:
        pass

result = {
    "task_start": TASK_START,
    "segment_report": {
        **stat(report_path),
        "columns": report_cols,
        "row_count": len(report_rows) if report_rows is not None else 0,
        "rows": report_rows or [],
    },
    "excluded_records": {
        **stat(excluded_path),
        "columns": excluded_cols,
        "row_count": len(excluded_rows) if excluded_rows is not None else 0,
        "rows": excluded_rows or [],
    },
    "audit_summary": {
        **stat(summary_path),
        "parse_error": summary_error,
        "value": summary,
    },
    "plot": {**plot, "is_valid_png": is_png},
}
print(json.dumps(result, indent=2))
PYEOF

chmod 666 /tmp/diamond_segment_audit_result.json 2>/dev/null || true

if [ ! -s /tmp/diamond_segment_audit_result.json ]; then
    echo "ERROR: result JSON is empty; python export failed"
    cat /tmp/diamond_segment_audit_export.err 2>/dev/null
fi

echo "=== Export Complete ==="
