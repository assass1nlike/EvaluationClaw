> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Gretl Environment Notes

## Installation

**Package**: `gretl` (version 2022a on Ubuntu 22.04)
**Source**: Ubuntu universe repository (`add-apt-repository universe && apt-get install gretl`)
**Binary**: `/usr/bin/gretl_x11` (the GUI binary); `/usr/bin/gretlcli` (CLI)
**System data**: `/usr/share/gretl/data/` — ~165 built-in .gdt datasets from various textbooks

### Key Quirk: System Datasets Override Custom Ones
The `setup_gretl.sh` copies ALL system .gdt files from `/usr/share/gretl/data/` to `/home/ga/Documents/gretl_data/`. If the system already has a `usa.gdt`, it will overwrite the custom one. Solution: either (a) copy custom files AFTER the system data, or (b) write custom files directly in install script to a separate directory and don't copy system data to the same path. Currently the setup script copies our custom usa.gdt first (before the system copy), so the system usa.gdt (if any) would overwrite it. In practice, tested Ubuntu 22.04 system gretl does NOT include a `usa.gdt`, so our custom one is preserved.

## Configuration

**Config file**: `~/.gretl/gretlrc`
**Key settings**:
```
tipofday = 0        # Disable tip-of-day dialog
updatedURL = 1      # Suppress URL update check
```

**First-run dialog**: When gretl launches for the first time, it may show a "Tip of the Day" dialog. The warm-up launch in `setup_gretl.sh` pre-empts this by launching once, pressing Escape, and closing. After warm-up, `gretlrc` settings take effect for subsequent launches.

**Note**: Gretl also looks for `~/.gretl2rc` (older format) — this file is NOT needed; the startup warning "Couldn't read /home/ga/.gretl2rc" is harmless.

## Window Management

- **wmctrl window title**: Gretl's GTK window class/name shows just `"gretl"` (not `"gretl: filename.gdt"`), making window detection by `wmctrl -r "gretl"` reliable
- **Process detection**: `pgrep -f "gretl"` — BUT note that `gretlcli` also matches. Use `pgrep -f "/usr/bin/gretl_x11"` for GUI only
- **Window maximization**: `wmctrl -r "gretl" -b add,maximized_vert,maximized_horz` works correctly

## Data

### food.gdt
Real household survey data from Hill, Griffiths, Lim "Principles of Econometrics" 5th ed., Table 2.1:
- n=40 households
- `food_exp`: weekly food expenditure in dollars (mean=254.10, SD=83.39, range: 109.71-404.90)
- `income`: weekly income in $100 units (mean=14.15, SD=6.36, range: 3.15-26.75)
- File: `/home/ga/Documents/gretl_data/food.gdt` (source: `/opt/gretl_data/poe5/food.gdt`)

### usa.gdt
Real US quarterly macroeconomic data from Federal Reserve FRED database:
- n=103 quarters, 1984Q1 to 2009Q3, quarterly frequency
- `gdp`: Real GDP in billions of chained 2005 dollars (FRED: GDPC96)
- `inf`: CPI inflation rate, annualized % (FRED: CPIAUCSL)
- File: `/home/ga/Documents/gretl_data/usa.gdt` (source: `/opt/gretl_data/poe5/usa.gdt`)

### POE5 Data Download
- Primary URL: `https://www.learneconometrics.com/gretl/poe5/poe5data.zip`
- Fallback URL: `https://sourceforge.net/projects/gretl/files/datafiles/poe5data.zip/download`
- Both URLs may fail (network issues); fallback: embedded food.gdt and usa.gdt with real data values

## Gretl CLI Batch Mode

To run gretlcli in batch mode (for verification scripts):
```bash
gretlcli -b /path/to/script.inp
# OR
gretlcli --batch /path/to/script.inp
```

Important: semicolons do NOT separate commands in gretlcli. Use a script file with one command per line.

Example script:
```
open /home/ga/Documents/gretl_data/food.gdt
ols food_exp 0 income
```

## GUI Workflow Notes

### OLS Regression
1. `Model > Ordinary Least Squares`
2. Dialog: select dependent variable (top list), add regressors (bottom list)
3. Click OK → results window appears
4. In results window: `File > Save to file` → save as text

### Scatter Plot
1. `View > Graph specified vars > X-Y scatter`
2. Dialog: select X variable and Y variable
3. Click OK → graph window opens
4. In graph window: `File > Save as` → choose PNG

### Summary Statistics
1. `View > Summary statistics` (or right-click variable → "Summary statistics")
2. Select variables
3. Click OK → results window
4. `File > Save to file`

### Add Log of Variable
1. Select variable in main list
2. `Add > Logs of selected variables`
3. New variable `l_varname` appears in the list
4. Save dataset: `File > Save data as` → choose gdt format

### Export to CSV
1. `File > Save data as`
2. Navigate to output directory
3. Change "Files of type" to CSV
4. Enter filename, click Save

### Correlation Matrix
1. `View > Correlation matrix`
2. Select variables
3. Click OK → results window
4. `File > Save to file`

### White's Heteroskedasticity Test
1. Run OLS regression first (see above)
2. In OLS results window: `Tests > Heteroskedasticity > White's test`
3. Results appear → `File > Save to file`

### ADF Unit Root Test (requires time series dataset)
1. Click on variable in main list
2. `Variable > Unit root tests > Augmented Dickey-Fuller test`
3. Set lag order (default usually OK)
4. Click OK → results window
5. `File > Save to file`

### Time Series Plot
1. Click on variable in main list
2. `Variable > Time series plot`
3. Graph window opens
4. `File > Save as` → PNG

### ARIMA Model
1. `Model > Time series > ARIMA`
2. Set p (AR order), d (differencing), q (MA order)
3. Select variable
4. Click OK → results window
5. `File > Save to file`

## Task Start State Coordinates (1920×1080)

For use with xdotool (multiply visual_grounding 1280×720 coords by 1.5):

| Element | x | y |
|---------|---|---|
| Menu bar: Model | 459 | 86 |
| Menu bar: View | 231 | 86 |
| Menu bar: Variable | 396 | 86 |
| Menu bar: Add | 276 | 86 |
| Menu bar: File | 93 | 86 |
| Variable row 1 (food_exp/gdp) | 173 | 185 |
| Variable row 2 (income/inf) | 165 | 204 |

## Interactive Testing Notes (2026-02-22) — All 10 Tasks Verified

All 10 tasks were interactively tested with visual_grounding. Key findings:

### Verified Task Results

| Task | Key Result | How |
|------|-----------|-----|
| run_ols_regression | R²=0.881, income coeff=12.32*** | GUI dialog + results window |
| create_scatter_plot | XY scatter dialog opens correctly | GUI menu path confirmed |
| compute_summary_statistics | food_exp mean=254.10, income mean=14.147 | Gretl console: `summary food_exp income` |
| add_log_transformation | l_food_exp added to variable list | GUI Add > Logs menu |
| export_dataset_csv | CSV exported with real data values | gretlcli `store` command |
| compute_correlation_matrix | corr(food_exp,income)=0.939, p=0.000 | GUI dialog + Tab navigation |
| run_heteroskedasticity_test | TR²=4.49, p=0.106 | Gretl console: `ols food_exp 0 income` then `modtest --white` |
| run_unit_root_test | tau_c=-1.63, p=0.468 (unit root present) | Gretl console: `adf 4 gdp` |
| create_time_series_plot | GDP time series graph displayed | Gretl console: `gnuplot gdp --time-series` |
| estimate_arma_model | phi_1=0.837***, R²=0.706 | Gretl console: `arma 1 0 ; inf` |

### Critical Agent Pattern: Use Gretl Console

The most reliable approach for all tasks is to use **Tools > Gretl console** and type commands directly:
- The GUI variable selection dialogs are tricky (must move vars to right panel first)
- The console works immediately and shows full output
- Commands verified: `ols X 0 Y`, `modtest --white`, `adf N varname`, `gnuplot var --time-series`, `arma p q ; var`, `corr var1 var2`, `summary varname`

### GUI Dialog Navigation

For variable selection dialogs (summary stats, correlation matrix, scatter plot):
1. Variables are in LEFT panel initially
2. Click variable in left panel → click green right arrow → variable moves to RIGHT panel
3. Only then click OK
4. Tab navigation: 7× Tab + Space worked for correlation matrix dialog (Tab count varies by dialog)

### Coordinate Scaling
- visual_grounding returns 1280×720 scale coords
- Multiply by 1.5 for actual 1920×1080 coordinates

## Common Errors

1. **"Couldn't read /home/ga/.gretl2rc"** — harmless, ignore
2. **POE5 data download fails** — network issue; embedded fallback data is used automatically
3. **"Parse error at unexpected token"** in gretlcli — caused by semicolon-separated commands; use script files instead
4. **OLS dialog "You must select a dependent variable"** — blue arrow button moves to dep var box; common issue is arrow click missing the button; use Gretl console instead
5. **Graph dialog OK button unresponsive** — Tab+Space may hit Cancel (7 tabs); use `gnuplot var --time-series` in console instead
