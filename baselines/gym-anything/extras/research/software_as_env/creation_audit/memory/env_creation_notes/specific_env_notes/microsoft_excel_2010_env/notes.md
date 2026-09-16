> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Microsoft Excel 2010 Environment - Creation Notes & Lessons Learned

## Overview

Created `microsoft_excel_2010_env` using the same proven Office 2010 Professional Plus MSI approach as the Word 2010 environment. This environment replaces the broken `microsoft_excel_env` which used Office 365 (ODT) and had an undismissable "Sign in to get started with Excel" dialog.

## Key Decisions

### Why Office 2010 (not Office 365)?
- Office 365 requires Microsoft account sign-in — blocks agent interaction
- Office 2010 Professional Plus has NO sign-in requirement
- Grace/trial mode works indefinitely without activation prompts
- MSI-based installer is predictable and reliable

### Why Professional Plus (not Starter)?
- Office 2010 Starter uses Click-to-Run (App-V 4.x) which is incompatible with Windows 11's built-in App-V 5.x
- Error: "Microsoft Application Virtualization is installed in an incompatible configuration"
- Professional Plus uses standard MSI installer — works perfectly on Windows 11

### Data Files
- Reused the 3 existing `.xlsx` files from the original `microsoft_excel_env`
- All contain real public data (US Census population, AAPL stock data, FRED retail sales)
- No synthetic data needed — existing files are high quality

## Installation Quirks

### Exit Code 3010
- Office 2010 MSI installer returns exit code 3010 = "reboot recommended"
- This is NOT an error — Excel works without rebooting
- Install script accepts both 0 and 3010 as success

### Coexistence with Word 2010
- Both Word and Excel 2010 can be installed on the same VM (tested)
- They share Office14 common files without conflicts
- Each env's config.xml specifies only the needed app

### ISO Download
- Source: Internet Archive (`archive.org/download/office2010nokeyneeded_201908/`)
- Size: ~731MB
- Install script validates size is >700MB before proceeding
- Uses BITS transfer with Invoke-WebRequest fallback

## Setup Script Notes

### schtasks Warm-up Time
- Use dynamic start time `(Get-Date).AddMinutes(1).ToString("HH:mm")` not `/ST 00:00`
- Using `/ST 00:00` causes a warning "Task may not run because /ST is earlier than current time"
- The task still runs via `/Run` but the warning is confusing

### Registry Keys (Office 14.0)
- `HKCU:\Software\Microsoft\Office\14.0\Common\General\ShownFirstRunOptin = 1`
- `HKCU:\Software\Microsoft\Office\14.0\FirstRun\BootedRTM = 1`
- `HKCU:\Software\Microsoft\Office\14.0\FirstRun\DisableMovie = 1`
- `HKCU:\Software\Microsoft\Office\14.0\Excel\Options\DisableBootToOfficeStart = 1`
- `HKCU:\Software\Microsoft\Office\14.0\Registration\AcceptAllEulas = 1`

### OneDrive
- Aggressively disabled via registry + uninstall
- Must kill OneDrive and OneDriveSetup processes
- Set `DisableFileSyncNGSC = 1` policy

## Task-Specific Notes

### Document Recovery Panel
- After force-killing Excel between tasks, a "Document Recovery" panel may appear on next launch
- Handled by clicking Close button at coordinates (216, 628) in `Dismiss-ExcelDialogsBestEffort`
- Panel appears on left side of spreadsheet area

### Task Data Ranges
- **sum_formula**: Population data in C2:C52 (51 rows: 50 states + DC)
- **create_chart**: Stock data starts row 2, has Date/Open/High/Low/Close/Volume columns
- **conditional_formatting**: Revenue in column E, all values >21,000 (real FRED data)

### Conditional Formatting Task Note
- Revenue values are all >21,000 (millions of dollars), so only the "green if >10,000" rule will visually apply
- The "red if <5,000" rule won't have any matching cells in the current data
- Task is still valid — tests agent's ability to set up conditional formatting rules

## File Structure

```
benchmarks/cua_world/environments/microsoft_excel_2010_env/
├── env.json                              # Environment config
├── scripts/
│   ├── install_excel.ps1                 # pre_start: Download & install Excel 2010
│   ├── setup_excel.ps1                   # post_start: Copy data, registry, warm-up
│   └── task_utils.ps1                    # Shared helpers (Find-ExcelExe, etc.)
├── data/
│   ├── office_config.xml                 # Excel-only install config
│   ├── us_census_population.xlsx         # US state population (Census Bureau)
│   ├── stock_market_data.xlsx            # AAPL stock prices
│   └── sales_report.xlsx                # US retail sales (FRED)
├── tasks/
│   ├── sum_formula/                      # Easy: enter SUM formula
│   ├── create_chart/                     # Medium: create line chart
│   └── conditional_formatting/           # Medium: apply conditional formatting
└── evidence_docs/
    ├── README.md                         # Full evidence with logs
    ├── sum_formula_start_state.png       # Population data loaded
    ├── sum_formula_completed.png         # SUM formula entered = 331,449,281
    ├── create_chart_start_state.png      # Stock data loaded
    └── conditional_formatting_start_state.png  # Sales data loaded
```

## Comparison with Original microsoft_excel_env

| Feature | Original (Office 365) | New (Office 2010) |
|---------|----------------------|-------------------|
| Sign-in required | YES (blocks agents) | NO |
| Activation | Required | Grace mode |
| Installer | ODT + XML config | MSI ISO + XML config |
| Install size | ~2GB | ~731MB ISO |
| First-run dialogs | "Sign in to get started" (blocking) | None observed |
| Ribbon | Modern | Classic 2010 (all features visible) |
| Tasks | Same 3 | Same 3 (reused data files) |
