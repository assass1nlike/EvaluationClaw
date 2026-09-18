# diamond_segment_audit

Pricing audit over the real `diamonds` price list: screen out physically
impossible measurements, aggregate 53,940 records into cut/color/clarity
segments, and deliver a table, an exclusion list, a reconciliation summary and
a chart.

## Why this task exists

It is a **hard step-budget** task. `init.max_steps` is 25, roughly a fifth of
what the environment's other analytical tasks allow. The work itself is not
exotic — the pressure comes from having to do it in a handful of agent steps.

An agent step is one model turn mapped onto one `env.step()` call, and a single
step can carry a whole action group (focus the console, type several thousand
characters, press Return). So one script that does the entire job costs about
three steps, while driving the same job through the GUI — inspecting the data,
computing segments one at a time, exporting each deliverable through a menu —
costs well over forty. The budget sits between those two paths. What is being
measured is whether the model picks the economical strategy *before* spending
its budget on the thorough one.

The budget is declared in the task description, so this is a deliberate choice
under a known constraint, not a trap.

## Data

`ggplot2::diamonds` — 53,940 round-cut diamonds with carat, cut, color,
clarity, depth, table, price and the x/y/z dimensions in mm. This is a real
retail price list (`ggplot2` documents it as such), and it is built into a
package that the environment already has installed, so the task needs no
network access. `setup_task.sh` also exports it to
`/home/ga/RProjects/datasets/diamonds.csv`.

## Deliverables

Written to `/home/ga/RProjects/output/`:

| File | Content |
|---|---|
| `segment_report.csv` | one row per segment with `n >= 150` valid records |
| `excluded_records.csv` | records with any of x, y, z equal to 0 |
| `audit_summary.json` | record and segment counts, plus a share that has to reconcile |
| `price_per_carat_by_segment.png` | top-20 segments by median price per carat |

## Verification

`verifier.py::verify_diamond_segment_audit` is fully programmatic — no VLM
call. Ground truth is computed in `setup_task.sh` from the same data and
written to `/tmp/diamond_segment_audit_gt.json`; the export script reports what
is on disk; the verifier compares the two.

Points: report structure 5, excluded set 10, summary counts 5, segment set 10,
segment statistics 55, reconciliation 5, plot 10. Pass at 80.

Gates:

- no `segment_report.csv` written during the task → 0;
- no ground-truth segment reproduced → 0 (wrong grouping or wrong dataset);
- any of `excluded_records.csv`, `audit_summary.json` or the plot missing,
  stale or invalid → score capped at 79, so a correct audit that omits one
  deliverable cannot pass.

The threshold sits above the 45 points reachable with perfect bookkeeping and
no correct segment statistics, so the analysis itself has to be right.

Extra reported segments dilute the statistics score rather than being ignored,
so dumping all 276 combinations scores below the threshold.
