> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# GNU Octave Environment - Creation Notes

## Installation

- **Method**: `apt-get install octave` on Ubuntu 22.04 (Jammy)
- **Version installed**: Octave 6.4.0
- **GUI launch command**: `octave --gui`
- **Additional packages**: octave-signal, octave-statistics, octave-io, octave-image, octave-optim, octave-struct, octave-control (installed with `|| true` fallback since some may not be available)
- **Dependencies**: gnuplot, gnuplot-x11 (for plotting), imagemagick (for screenshots), x11-utils (for xwd)

## Key Quirks

### 1. VNC Password Must Be Explicitly Set
The framework's `VNCSpec` defaults `password=None`. The runner uses `vnc_cfg.password if vnc_cfg else "password"`, but since VNCSpec always exists via `default_factory`, the check passes and password remains None. This causes VNC connection to fail silently (process hangs forever).

**Fix**: Add `"vnc": {"password": "password"}` to env.json.

### 2. First-Run Dialog (Community News)
On first launch, Octave shows a "Community News" dialog that can block the GUI. The `.octaverc` setting `news/allow_web_connection=false` helps but isn't sufficient alone.

**Fix**: Warm-up launch in post_start hook:
1. Launch Octave GUI
2. Wait for window (poll with xdotool search)
3. Press Escape to dismiss dialog
4. Kill Octave
5. Task setup then launches a fresh Octave that skips the dialog

### 3. Graphics Toolkit for Headless Plotting
Octave's default `qt` graphics toolkit requires a running X display for rendering. For reliable off-screen plotting (saving PNGs without displaying), use:
```matlab
graphics_toolkit('gnuplot');
```
Set this in `.octaverc` so all sessions use it.

### 4. CSV Data Loading
- **Numeric-only CSV**: Use `csvread('file.csv', 1, 0)` (skip header row)
- **Mixed data (strings + numbers)**: Use `pkg load io; csv2cell('file.csv')` from the io package
- The earthquake and auto_mpg datasets have mixed data (strings in header, some text columns)

### 5. Octave Window Title
- wmctrl identifies the window as "Octave" (case-sensitive)
- xdotool search uses `--name "Octave"` pattern
- The window title changes to include the current directory

## Datasets

### Iris Dataset (iris.csv)
- Source: UCI Machine Learning Repository (archive.ics.uci.edu)
- 150 rows, 5 columns: sepal_length, sepal_width, petal_length, petal_width, species
- Species are text: "Iris-setosa", "Iris-versicolor", "Iris-virginica"
- Column 5 (species) maps to numeric: setosa=1, versicolor=2, virginica=3 when loaded with csvread (text becomes 0)
- For proper species handling, use the io package's csv2cell

### Earthquakes Dataset (earthquakes_2024_jan.csv)
- Source: USGS Earthquake Catalog API
- 1350 rows, 22 columns
- Key columns: time(1), latitude(2), longitude(3), depth(4), mag(5)
- All earthquake records from January 2024 with magnitude >= 4.0
- Has text columns (time, place, type) - use csv2cell for full parsing

### Auto MPG Dataset (auto_mpg.csv)
- Source: UCI Machine Learning Repository
- 398 rows, 9 columns: mpg, cylinders, displacement, horsepower, weight, acceleration, model_year, origin, car_name
- Some horsepower values are "?" (missing) - need filtering
- car_name column is text - use csv2cell for full parsing

## Timing

- VM boot + SSH available: ~15s
- pre_start (install): ~75s
- post_start (setup + warmup): ~18s
- pre_task (launch Octave): ~19s
- Total: ~112s

## Screenshot Method

Use `xwd -root` (not `scrot`) on GNOME:
```bash
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xwd -root -out /tmp/screen.xwd
convert /tmp/screen.xwd /tmp/screen.png
```
