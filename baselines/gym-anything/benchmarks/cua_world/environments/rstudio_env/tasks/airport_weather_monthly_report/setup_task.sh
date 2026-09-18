#!/bin/bash
echo "=== Setting up Airport Weather Monthly Report Task ==="

. /workspace/scripts/task_utils.sh 2>/dev/null || true

# Files copied into a task dir after the checkpoint was built arrive without +x.
chmod +x /workspace/tasks/airport_weather_monthly_report/export_result.sh 2>/dev/null || true

if ! type take_screenshot &>/dev/null; then
    take_screenshot() {
        DISPLAY=:1 import -window root "${1:-/tmp/screenshot.png}" 2>/dev/null || \
        DISPLAY=:1 scrot "${1:-/tmp/screenshot.png}" 2>/dev/null || true
    }
fi

if ! type is_rstudio_running &>/dev/null; then
    is_rstudio_running() { pgrep -f "rstudio" > /dev/null 2>&1; }
    focus_rstudio() { local w=$(DISPLAY=:1 wmctrl -l 2>/dev/null | grep -i rstudio | head -1 | awk '{print $1}'); [ -n "$w" ] && DISPLAY=:1 wmctrl -i -a "$w"; }
    maximize_rstudio() { local w=$(DISPLAY=:1 wmctrl -l 2>/dev/null | grep -i rstudio | head -1 | awk '{print $1}'); [ -n "$w" ] && DISPLAY=:1 wmctrl -i -r "$w" -b add,maximized_vert,maximized_horz; }
fi

OUT=/home/ga/RProjects/output
DATA=/home/ga/RProjects/datasets/nyc_weather_2013.csv
mkdir -p "$OUT" /home/ga/RProjects/datasets
rm -rf "${OUT:?}"/* 2>/dev/null || true

# ── Real data: NOAA hourly surface observations, via the nycflights13 project ───
# weather.csv in tidyverse/nycflights13 is the 2013 record for EWR/JFK/LGA
# assembled from the NOAA Integrated Surface Database and the Iowa Environmental
# Mesonet ASOS archive. 26,115 hourly rows. No synthetic data anywhere.
MIN_BYTES=2000000
rm -f "$DATA"
for URL in \
    "https://raw.githubusercontent.com/tidyverse/nycflights13/main/data-raw/weather.csv" \
    "https://raw.githubusercontent.com/tidyverse/nycflights13/master/data-raw/weather.csv" \
    ; do
    [ "$(stat -c%s "$DATA" 2>/dev/null || echo 0)" -ge "$MIN_BYTES" ] && break
    rm -f "$DATA"
    wget -q --timeout=60 -O "$DATA" "$URL" 2>/dev/null || true
    [ "$(stat -c%s "$DATA" 2>/dev/null || echo 0)" -ge "$MIN_BYTES" ] && break
    rm -f "$DATA"
    curl -s --max-time 60 -o "$DATA" "$URL" 2>/dev/null || true
done

if [ "$(stat -c%s "$DATA" 2>/dev/null || echo 0)" -lt "$MIN_BYTES" ]; then
    echo "ERROR: could not download the NOAA weather dataset"
    exit 1
fi
chown -R ga:ga /home/ga/RProjects

# ── Ground truth ───────────────────────────────────────────────────────────────
R --vanilla --slave -e '
w <- read.csv("/home/ga/RProjects/datasets/nyc_weather_2013.csv", stringsAsFactors = FALSE)
w$origin <- as.character(w$origin)

adverse <- (!is.na(w$wind_speed) & w$wind_speed >= 25) | (!is.na(w$precip) & w$precip >= 0.25)

adv <- w[adverse, c("origin", "month", "day", "hour", "temp", "wind_speed", "precip")]
write.csv(adv, "/tmp/airport_weather_monthly_report_gt_adverse.csv", row.names = FALSE)

key <- paste(w$origin, w$month, sep = "|")
keys <- sort(unique(key))
stats <- data.frame(
    origin = sub("\\|.*", "", keys),
    month = as.integer(sub(".*\\|", "", keys)),
    n_hours = as.integer(tapply(w$temp, key, length)[keys]),
    mean_temp_f = as.numeric(tapply(w$temp, key, mean, na.rm = TRUE)[keys]),
    mean_wind_speed_mph = as.numeric(tapply(w$wind_speed, key, mean, na.rm = TRUE)[keys]),
    total_precip_in = as.numeric(tapply(w$precip, key, sum, na.rm = TRUE)[keys]),
    n_adverse_hours = as.integer(tapply(adverse, key, sum)[keys]),
    stringsAsFactors = FALSE
)
stats <- stats[order(stats$origin, stats$month), ]
write.csv(stats, "/tmp/airport_weather_monthly_report_gt_stats.csv", row.names = FALSE)

totals <- data.frame(
    total_hours = nrow(w),
    adverse_hours_total = sum(adverse),
    n_station_months = nrow(stats),
    mean_temp_f_all = round(mean(w$temp, na.rm = TRUE), 2)
)
write.csv(totals, "/tmp/airport_weather_monthly_report_gt_totals.csv", row.names = FALSE)
cat("GT: hours", nrow(w), "adverse", sum(adverse), "station-months", nrow(stats), "\n")
' 2>&1 | tail -3

python3 << 'PYEOF'
import csv, json

stats = list(csv.DictReader(open("/tmp/airport_weather_monthly_report_gt_stats.csv")))
adv = list(csv.DictReader(open("/tmp/airport_weather_monthly_report_gt_adverse.csv")))
tot = list(csv.DictReader(open("/tmp/airport_weather_monthly_report_gt_totals.csv")))[0]

gt = {
    "total_hours": int(tot["total_hours"]),
    "adverse_hours_total": int(tot["adverse_hours_total"]),
    "n_station_months": int(tot["n_station_months"]),
    "mean_temp_f_all": float(tot["mean_temp_f_all"]),
    "stations": sorted({r["origin"] for r in stats}),
    "adverse_keys": [[r["origin"], int(r["month"]), int(r["day"]), int(r["hour"])] for r in adv],
    "stats": [
        {
            "origin": r["origin"],
            "month": int(r["month"]),
            "n_hours": int(r["n_hours"]),
            "mean_temp_f": float(r["mean_temp_f"]),
            "mean_wind_speed_mph": float(r["mean_wind_speed_mph"]),
            "total_precip_in": float(r["total_precip_in"]),
            "n_adverse_hours": int(r["n_adverse_hours"]),
        }
        for r in stats
    ],
}
json.dump(gt, open("/tmp/airport_weather_monthly_report_gt.json", "w"), indent=2)
print("GT:", {k: v for k, v in gt.items() if k not in ("stats", "adverse_keys")},
      "adverse rows", len(gt["adverse_keys"]), "stats rows", len(gt["stats"]))
PYEOF

date +%s > /tmp/airport_weather_monthly_report_start_ts

if ! is_rstudio_running; then
    su - ga -c "DISPLAY=:1 R_LIBS_USER=/home/ga/R/library rstudio /home/ga/RProjects/welcome.R" >/dev/null 2>&1 &
    for _ in $(seq 1 30); do
        DISPLAY=:1 wmctrl -l 2>/dev/null | grep -qi rstudio && break
        sleep 2
    done
fi
focus_rstudio
maximize_rstudio
sleep 2
take_screenshot /tmp/airport_weather_monthly_report_start_screenshot.png

echo "=== Task ready: nyc_weather_2013.csv in /home/ga/RProjects/datasets ==="
