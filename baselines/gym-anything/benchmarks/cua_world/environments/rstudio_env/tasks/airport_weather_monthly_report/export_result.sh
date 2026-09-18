#!/bin/bash
echo "=== Exporting Airport Weather Monthly Report Result ==="

rm -f /tmp/airport_weather_monthly_report_result.json 2>/dev/null || \
    sudo rm -f /tmp/airport_weather_monthly_report_result.json 2>/dev/null || true

TASK_START=$(cat /tmp/airport_weather_monthly_report_start_ts 2>/dev/null || echo "0")

DISPLAY=:1 import -window root /tmp/airport_weather_monthly_report_end_screenshot.png 2>/dev/null || \
    DISPLAY=:1 scrot /tmp/airport_weather_monthly_report_end_screenshot.png 2>/dev/null || true

python3 << 'PYEOF' > /tmp/airport_weather_monthly_report_result.json 2>/tmp/airport_weather_monthly_report_export.err
import csv, json, os

OUT = "/home/ga/RProjects/output"
TASK_START = 0
try:
    TASK_START = int(open("/tmp/airport_weather_monthly_report_start_ts").read().strip())
except Exception:
    pass

STATIONS = ["EWR", "JFK", "LGA"]
MONTHS = ["%02d" % m for m in range(1, 13)]
EXPECTED_FIGURES = ["{}_{}.png".format(s, m) for s in STATIONS for m in MONTHS]


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


def read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        return {"__error__": str(e)}


stats_path = os.path.join(OUT, "monthly_station_stats.csv")
adverse_path = os.path.join(OUT, "adverse_hours.csv")
summary_path = os.path.join(OUT, "report_summary.json")
fig_dir = os.path.join(OUT, "figures")

stats_rows = read_csv(stats_path)
adverse_rows = read_csv(adverse_path)

figures = {}
for name in EXPECTED_FIGURES:
    path = os.path.join(fig_dir, name)
    info = stat(path)
    is_png = False
    if info["exists"]:
        try:
            with open(path, "rb") as f:
                is_png = f.read(8) == b"\x89PNG\r\n\x1a\n"
        except Exception:
            pass
    info["is_valid_png"] = is_png
    figures[name] = info

result = {
    "task_start": TASK_START,
    "monthly_station_stats": {
        **stat(stats_path),
        "columns": list(stats_rows[0].keys()) if stats_rows else [],
        "rows": stats_rows or [],
    },
    "adverse_hours": {
        **stat(adverse_path),
        "columns": list(adverse_rows[0].keys()) if adverse_rows else [],
        "rows": adverse_rows or [],
    },
    "report_summary": {**stat(summary_path), "value": read_json(summary_path)},
    "figures": figures,
}
print(json.dumps(result, indent=2))
PYEOF

chmod 666 /tmp/airport_weather_monthly_report_result.json 2>/dev/null || true

if [ ! -s /tmp/airport_weather_monthly_report_result.json ]; then
    echo "ERROR: result JSON is empty; python export failed"
    cat /tmp/airport_weather_monthly_report_export.err 2>/dev/null
fi

echo "=== Export Complete ==="
