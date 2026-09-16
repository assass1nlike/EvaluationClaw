> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# NinjaTrader Environment - Lessons Learned

## Version and Licensing

- **Installed version**: NinjaTrader 8.1.3.x (release.240331-1435) from `NinjaTrader.Install.V8.msi`
- **License mode**: Enterprise Evaluation (63-day trial, no login required)
- **SIM license key**: `@SIM-A82F-D583-40B1-AE74-B79F-705D-1952` (free, no expiration) — not needed for evaluation mode
- **Key advantage**: Unlike current 8.1.x releases that require mandatory login, the evaluation period provides full functionality without any authentication
- **Original plan** targeted 8.0.28.0 (no login at all) but the MSI provided installed 8.1.3.x which also doesn't require login during evaluation

## Critical: Win32 API Clicks Don't Work for NinjaTrader

**Problem**: The schtasks/Win32 API approach used successfully in the Power BI Desktop environment (`SetCursorPos` + `mouse_event` via P/Invoke) does NOT work for NinjaTrader windows. Clicks are silently ignored.

**Root cause**: Unknown. Possibly related to NinjaTrader's WPF rendering, UIPI (User Interface Privilege Isolation), or custom window message handling.

**Solution**: Use the **PyAutoGUI TCP server** (port 5555 inside the VM) instead. The server runs in the interactive desktop session (Session 1) and accepts JSON commands over TCP. From SSH (Session 0), PowerShell scripts connect to `localhost:5555` and send click/keyboard commands.

**Implementation**:
- `task_utils.ps1` has `Send-PyAutoGUI`, `PyAutoGUI-Click`, `PyAutoGUI-Press`, `PyAutoGUI-Hotkey`, `PyAutoGUI-Write` functions
- `dismiss_dialogs.ps1` uses these functions (no schtasks needed for dialog dismissal)
- Task setup scripts call `dismiss_dialogs.ps1` directly (not via schtasks)

## Dialog Sequence (1280x720)

### First launch:
1. **"Get Connected"** - Connect to live data feed → click Skip at (749, 463)
2. **"Warning"** - Windows outside viewable range → click Yes at (677, 372)
3. **"Getting Started"** - Tips panel (Tip 2/3 of 7) → click X at (618, 167)
4. **SuperDOM** - May open as default workspace window

### Subsequent launches (from checkpoint):
1. **"Warning"** - Windows outside viewable range → click Yes at (677, 372)
2. **"Getting Started"** - Tips panel → click X at (618, 167)
3. **SuperDOM** - May reappear

### Important: Do NOT attempt to close SuperDOM via fixed coordinates
The SuperDOM X button at (819, 11) is too close to the PyAutoGUI server terminal's close button. Accidentally clicking it kills the PyAutoGUI server.

## Data Import

- **Format**: NinjaTrader semicolon-delimited TXT (`yyyyMMdd;open;high;low;close;volume`)
- **File naming**: `<TICKER>.Last.txt` (e.g., `AAPL.Last.txt`)
- **Import path**: Tools → Import → Historical Data → Import button → browse to file
- **Import settings**: Format = "NinjaTrader (end of bar timestamps)", Data Type = "Last", Time Zone = "UTC"
- **Result**: 502 records per file imported successfully
- **Data storage**: `C:\Users\Docker\Documents\NinjaTrader 8\db\day\<TICKER>\`
- **Data source**: Yahoo Finance daily OHLCV (Jan 2023 - Dec 2024) for SPY, AAPL, MSFT

## Automation Architecture

```
SSH (Session 0)                    Interactive Session (Session 1)
    |                                       |
    |-- schtasks /IT --------> Launch NinjaTrader.exe
    |                                       |
    |-- TCP localhost:5555 --> PyAutoGUI Server (click/type/etc.)
    |                                       |
    |-- PowerShell scripts                  |
    |   (task_utils.ps1)                    |
    |   (dismiss_dialogs.ps1)               |
    |   (import_data.ps1)                   |
```

## Installation

- **MSI**: `NinjaTrader.Install.V8.msi` (67MB), silent install via `msiexec.exe /i /qn /norestart`
- **Install path**: `C:\Program Files\NinjaTrader 8\bin\NinjaTrader.exe` (note: `Program Files` not `Program Files (x86)`)
- **Install time**: ~127 seconds (pre_start hook)
- **Post-start time**: ~42 seconds (including warm-up)
- **Process name**: `NinjaTrader.exe`
- **Interactive session**: Session 1 (Console)

## Files Created

| File | Purpose |
|------|---------|
| `env.json` | Environment configuration |
| `scripts/install_ninjatrader.ps1` | Silent MSI installation |
| `scripts/setup_ninjatrader.ps1` | Post-boot setup, OneDrive removal, warm-up, data import |
| `scripts/task_utils.ps1` | PyAutoGUI TCP helpers, Find-NTExe, Launch-NTInteractive |
| `scripts/dismiss_dialogs.ps1` | Dismiss startup dialogs via PyAutoGUI TCP |
| `scripts/import_data.ps1` | Import Yahoo Finance data via UI automation |
| `data/SPY.Last.txt` | S&P 500 ETF daily OHLCV 2023-2024 (502 rows) |
| `data/AAPL.Last.txt` | Apple daily OHLCV 2023-2024 (502 rows) |
| `data/MSFT.Last.txt` | Microsoft daily OHLCV 2023-2024 (502 rows) |
| `data/NinjaTrader.Install.V8.msi` | NinjaTrader installer (67MB) |
| `tasks/add_indicator/` | Easy task: Add SMA(20) to SPY chart |
| `tasks/create_chart_layout/` | Medium task: Create AAPL chart with EMA, RSI, MACD |
| `tasks/run_backtest/` | Medium task: Backtest SampleMACrossOver on MSFT |
