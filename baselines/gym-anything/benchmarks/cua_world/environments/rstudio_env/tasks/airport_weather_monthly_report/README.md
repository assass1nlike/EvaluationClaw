# airport_weather_monthly_report

2013 weather review for EWR, JFK and LGA: aggregate the real NOAA hourly
observation record into 36 station-month rows, pull out the adverse hours, and
produce 36 charts.

## Why this task exists

It is a **hard step-budget** task. `init.max_steps` is 18. The analysis is
routine; the volume is not — 36 figures is far more than anyone can produce
one at a time.

An agent step is one model turn mapped onto one `env.step()` call, and a single
step can carry a whole action group (focus the console, type a multi-thousand
character script, press Return). A loop that writes all 36 PNGs costs a few
steps. The same 36 figures produced the obvious way — plot in the GUI, open the
export dialog, name the file, repeat — costs several steps each, so the budget
is gone long before the job is. What is being measured is whether the model
recognises that the economical path is to script the output rather than drive
it, *before* it has spent the budget proving the thorough path unaffordable.

The budget is declared in the task description, so this is a deliberate choice
under a known constraint, not a trap.

## Data

NOAA hourly surface observations for 2013, the `data-raw/weather.csv` file from
the `tidyverse/nycflights13` project — 26,115 rows assembled from the NOAA
Integrated Surface Database and the Iowa Environmental Mesonet ASOS archive.
`setup_task.sh` downloads it (with a byte floor, and it fails loudly rather
than substituting anything) to
`/home/ga/RProjects/datasets/nyc_weather_2013.csv`.

## Deliverables

Written to `/home/ga/RProjects/output/`:

| File | Content |
|---|---|
| `monthly_station_stats.csv` | 36 station-month rows with counts, means and precip totals |
| `adverse_hours.csv` | every hour with wind_speed >= 25 mph or precip >= 0.25 in |
| `report_summary.json` | headline counts and the file-wide mean temperature |
| `figures/{ORIGIN}_{MM}.png` | 36 daily-mean-temperature bar charts |

## Verification

`verifier.py::verify_airport_weather_monthly_report` is fully programmatic — no
VLM call. Ground truth is computed in `setup_task.sh` from the same data and
written to `/tmp/airport_weather_monthly_report_gt.json`; the export script
reports what is on disk; the verifier compares the two.

Points: stats structure 5, station-month coverage 10, station-month statistics
45, adverse hour set 15, summary fields 5, figures 20. Pass at 80.

Gates:

- no `monthly_station_stats.csv` written during the task → 0;
- no ground-truth station-month reproduced → 0 (wrong file or wrong grouping);
- any deliverable missing or invalid, fewer than 30 valid figures, or fewer
  than 90% of the station-month rows correct → score capped at 79.

The cap is what puts the 36 figures inside the pass condition: a correct
tabulation that skips the charts, or that only manages a handful of them,
cannot reach the threshold.
