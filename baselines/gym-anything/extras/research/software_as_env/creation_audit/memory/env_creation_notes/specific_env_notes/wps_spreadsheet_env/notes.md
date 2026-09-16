> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# WPS Spreadsheet Environment Notes

## Application Overview
- **WPS Office Spreadsheet** (command: `et`): Part of WPS Office for Linux
- **Version**: v11.1.0.11723 (free personal edition)
- **Package**: wps-office_11.1.0.11723.XA_amd64.deb
- **Install Source**: Direct download from WPS CDN
- **Shares**: Same WPS installation as wps_office_writer_env (`wps` for writer, `et` for spreadsheet, `wpp` for presentation)

## Architecture
- Qt-based desktop application with ribbon UI
- Config stored in `~/.config/Kingsoft/Office.conf` (INI-format with Qt variant serialization)
- EULA acceptance stored in `[6.0]` section: `common\AcceptedEULA=true`
- System Check dialog warns about missing fonts (cosmetic, can be dismissed)
- Files saved as `.xlsx` (OpenXML), fully compatible with openpyxl for verification

## Data Sources (Real Data)
All task data is derived from real public datasets:
- **Kaggle Superstore Sales** (9800 rows): Used for sales_data.csv, employee_sales.csv, customer_orders.csv, project_tracker.csv
- **Data.gov Montgomery County MD Warehouse & Retail Sales**: Used for inventory.csv
- Data stored in `data/` directory, mounted read-only at `/workspace/data/`
- Setup scripts read CSV files and create formatted .xlsx files via openpyxl (Python)

## Key Learnings

### EULA Handling
- WPS shows EULA dialog on first launch even with pre-populated config
- Must launch WPS during setup, accept via xdotool clicks, then wait for config save
- Checkbox coordinates (1280x720): (429, 432); Confirm button: (860, 432)
- Scale to 1920x1080: multiply by 1.5 → (644, 648) and (1290, 648)
- Config key for suppression: `[6.0] common\AcceptedEULA=true`

### System Check Dialog
- Appears after EULA, warns about missing font symbols
- **DO NOT** use `wmctrl -c 'System Check'` — unreliable
- Instead: activate with `wmctrl -ia $WINID`, then `xdotool key alt+F4`
- Does not block spreadsheet functionality

### WPS Office Default App Dialog
- Asks "Set WPS as default office software?"
- Appears after System Check on first launch
- Dismiss: activate with `wmctrl -ia $WINID`, then `xdotool key Return` (presses OK)

### Dialog Dismissal Strategy (CRITICAL)
- Three dialogs appear on first launch: System Check, "Checking completed", WPS Office default
- Must dismiss front-to-back (topmost first): WPS Office → System Check → Checking completed
- Use retry loop (up to 3 attempts) since dialogs may appear with delays
- Shared helper: `source /workspace/scripts/launch_wps_for_task.sh` provides:
  - `launch_wps_with_file <path>` — full launch + dialog handling + maximize
  - `dismiss_wps_dialogs` — lightweight check-and-dismiss for already-running WPS

### Process Management (CRITICAL)
- **NEVER** use `pkill -f "et"` - matches gnome-settings-daemon, NetworkManager, etc., crashes desktop
- Use `pkill -x et` (exact process name match) or `pkill -f "/office6/et"`
- Same applies for `pkill -f "wps"` → use `pkill -x wps` instead

### GDM Auto-Login
- Configure with `AutomaticLoginEnable=true` and `AutomaticLogin=ga` in `/etc/gdm3/custom.conf`
- Must use `WaylandEnable=false` for X11 compatibility
- After checkpoint restore, GDM may show login screen; restart GDM with `systemctl restart gdm3`
- X11 auth: copy GDM's Xauthority from Xorg process to `/home/ga/.Xauthority`

### Verification with openpyxl
- WPS saves standard .xlsx files readable by openpyxl
- Conditional formatting: check `ws.conditional_formatting` rules
- Data validation: check `ws.data_validations.dataValidation`
- AutoFilter: check `ws.auto_filter.ref`
- Formulas: read cell values with `data_only=False` to see formulas
- Pivot tables: WPS stores in `ws._pivots` (openpyxl has limited pivot table reading)

## Tasks Created

| Task | Difficulty | Data Source | Verifier Criteria |
|------|-----------|-------------|-------------------|
| create_sales_summary | medium | Superstore Sales (60 rows) | "Summary" sheet exists, SUMIF/AVERAGEIF/COUNTIF formulas, bold headers, currency formatting |
| add_conditional_formatting | medium | Warehouse Sales (30 items) | Conditional formatting rules on Quantity column, red for low stock |
| create_pivot_table | hard | Superstore Aggregated (20 rows) | "Pivot Summary" sheet exists with aggregated data or pivot table |
| apply_data_validation | medium | Superstore Orders (12 projects) | Data validation on Status/Priority columns, dropdown lists, freeze panes |
| sort_and_filter_data | medium | Superstore Orders (40 orders) | AutoFilter enabled, sorted by Amount descending, freeze panes |

## Baseline Verification Results
All 5 tasks baseline = 0 (verified Feb 13, 2026):
- create_sales_summary: 0 (Summary sheet NOT found)
- add_conditional_formatting: 0 (Conditional formatting NOT found)
- create_pivot_table: 0 (Multiple sheets NOT found)
- apply_data_validation: 0 (Data validation NOT found)
- sort_and_filter_data: 0 (AutoFilter NOT found)

## Fixes Applied (March 2026)

### Issues Fixed
1. **Missing mount directories**: Created `config/` and `assets/` directories (were referenced in env.json but didn't exist)
2. **Incomplete post_start dialog handling**: Rewrote warm-up launch to properly dismiss all 3 dialog types with retry loop
3. **5 tasks didn't launch WPS**: `create_sales_summary`, `create_pivot_table`, `sort_and_filter_data`, `calculate_manufacturing_oee`, `farm_soil_nutrient_analysis` — now all use shared helper
4. **Missing `apply_data_validation` task**: Created complete task (listed in seed_tasks.json but directory was missing)
5. **62 tasks without dialog dismissal**: Added `dismiss_wps_dialogs` call to all tasks that launch WPS inline
6. **5 very_hard tasks**: Replaced inline launch with shared helper for consistent dialog handling

### New Files
- `scripts/launch_wps_for_task.sh` — shared helper with `launch_wps_with_file()` and `dismiss_wps_dialogs()`
- `tasks/apply_data_validation/` — complete task directory (task.json, setup_task.sh, export_result.sh, verifier.py)
- `config/.gitkeep`, `assets/.gitkeep` — placeholder files for mount directories

## Timing
- Install time (fresh, no cache): ~105-110s (WPS deb download + install)
- Setup time (post_start): ~60-70s (includes robust dialog handling with retry)
- Task setup time: ~11-12s each (Python xlsx creation + WPS launch + dialog check)
- Verification time: ~25s each (includes VLM attempt timeouts when unavailable)
