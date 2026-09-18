#!/bin/bash
echo "=== Setting up Diamond Segment Audit Task ==="

. /workspace/scripts/task_utils.sh 2>/dev/null || true

# Files copied into a task dir after the checkpoint was built arrive without +x.
chmod +x /workspace/tasks/diamond_segment_audit/export_result.sh 2>/dev/null || true

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
mkdir -p "$OUT"
mkdir -p /home/ga/RProjects/datasets
rm -rf "${OUT:?}"/* 2>/dev/null || true

# ── Ground truth ───────────────────────────────────────────────────────────────
# Real data: the `diamonds` dataset shipped with the ggplot2 package (a real
# 2008 retail price list of 53,940 round-cut diamonds). No synthetic data.
R --vanilla --slave -e '
suppressPackageStartupMessages(library(ggplot2))
d <- diamonds
writeLines(as.character(nrow(d)), "/tmp/diamond_segment_audit_gt_total.txt")
write.csv(d, "/home/ga/RProjects/datasets/diamonds.csv", row.names = FALSE)

bad <- d$x == 0 | d$y == 0 | d$z == 0
excluded <- d[bad, c("carat", "cut", "color", "clarity", "depth", "table", "price", "x", "y", "z")]
valid <- d[!bad, ]
valid$ppc <- valid$price / valid$carat

k <- paste(valid$cut, valid$color, valid$clarity, sep = "|")
combos <- data.frame(combo = names(table(k)), n = as.integer(table(k)), stringsAsFactors = FALSE)
write.csv(combos, "/tmp/diamond_segment_audit_gt_combos.csv", row.names = FALSE)

segs <- data.frame(
    combo = names(table(k)),
    n = as.integer(tapply(valid$price, k, length)),
    median_price = as.numeric(tapply(valid$price, k, median)),
    median_price_per_carat = as.numeric(tapply(valid$ppc, k, median)),
    iqr_price_per_carat = as.numeric(tapply(valid$ppc, k, IQR)),
    stringsAsFactors = FALSE
)
parts <- do.call(rbind, strsplit(segs$combo, "|", fixed = TRUE))
segs$cut <- parts[, 1]; segs$color <- parts[, 2]; segs$clarity <- parts[, 3]
segs <- segs[order(segs$cut, segs$color, segs$clarity), ]
rep <- segs[segs$n >= 150, c("cut", "color", "clarity", "n", "median_price",
                             "median_price_per_carat", "iqr_price_per_carat")]
write.csv(rep, "/tmp/diamond_segment_audit_gt_segments.csv", row.names = FALSE)
write.csv(excluded, "/tmp/diamond_segment_audit_gt_excluded.csv", row.names = FALSE)
cat("GT: total", nrow(d), "excluded", nrow(excluded), "reported segments", nrow(rep), "\n")
' 2>&1 | tail -3

python3 << 'PYEOF'
import csv, json

total = int(open("/tmp/diamond_segment_audit_gt_total.txt").read().strip())
combos = list(csv.DictReader(open("/tmp/diamond_segment_audit_gt_combos.csv")))
segs = list(csv.DictReader(open("/tmp/diamond_segment_audit_gt_segments.csv")))
exc = list(csv.DictReader(open("/tmp/diamond_segment_audit_gt_excluded.csv")))

valid = total - len(exc)
records_in_reported = sum(int(r["n"]) for r in segs)
gt = {
    "total_records": total,
    "excluded_records": len(exc),
    "valid_records": valid,
    "segments_total": len(combos),
    "segments_reported": len(segs),
    "records_in_reported_segments": records_in_reported,
    "share_in_reported_segments": round(records_in_reported / valid, 4),
}
json.dump(gt, open("/tmp/diamond_segment_audit_gt.json", "w"), indent=2)
print("GT summary:", gt)
PYEOF

chown -R ga:ga /home/ga/RProjects

date +%s > /tmp/diamond_segment_audit_start_ts

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
take_screenshot /tmp/diamond_segment_audit_start_screenshot.png

echo "=== Task ready: diamonds.csv written to /home/ga/RProjects/datasets ==="
