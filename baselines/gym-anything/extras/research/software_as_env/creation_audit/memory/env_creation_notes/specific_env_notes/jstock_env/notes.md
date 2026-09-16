> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# JStock Environment Notes

## Overview
JStock 1.0.7.60 — free Java Swing stock portfolio management app.
- Download: `https://github.com/yccheok/jstock/releases/download/release_1-0-7-60/jstock-1.0.7.60-jre-linux.zip`
- Installed to: `/opt/jstock/` with bundled JRE
- Launcher: `/opt/jstock/jstock.sh`
- Data dir: `~/.jstock/1.0.7/`

## CRITICAL: JStock Data File Paths

JStock maps country names to Java enum names for filesystem storage:
```
"United States"  →  UnitedState   (no space, singular, camelCase)
```

Correct paths (verified by running JStock and inspecting filesystem):
```
Watchlist:  ~/.jstock/1.0.7/UnitedState/watchlist/My Watchlist/realtimestock.csv
Portfolio:  ~/.jstock/1.0.7/UnitedState/portfolios/My Portfolio/buyportfolio.csv
            (NOTE: "portfolios" plural, not "portfolio")
```

Common mistakes:
- Using `United States/` → wrong, JStock uses `UnitedState/`
- Using `watchlist/Default/` → wrong, JStock default is `watchlist/My Watchlist/`
- Using `portfolio/Default/` → wrong, JStock uses `portfolios/My Portfolio/`
- Using `buytransaction.csv` → wrong, JStock uses `buyportfolio.csv`

## CRITICAL: CSV File Formats

### realtimestock.csv (Watchlist)
```csv
"timestamp=0"
"Code","Symbol","Prev","Open","Last","High","Low","Vol","Chg","Chg (%)","L.Vol","Buy","B.Qty","Sell","S.Qty","Fall Below","Rise Above"
"AAPL","AAPL","0.0","0.0","0.0","0.0","0.0","0","0.0","0.0","0","0.0","0","0.0","0","0.0","0.0"
```
- First line MUST be `"timestamp=0"` (quoted)
- All values are double-quoted
- 17 columns
- Prices default to 0.0 (fetched live from Yahoo Finance when online)
- Fall Below / Rise Above: 0.0 means no alert set

### buyportfolio.csv (Portfolio Buy Transactions)
```csv
"Code","Symbol","Date","Units","Purchase Price","Current Price","Purchase Value","Current Value","Gain/Loss Price","Gain/Loss Value","Gain/Loss %","Broker","Clearing Fee","Stamp Duty","Net Purchase Value","Net Gain/Loss Value","Net Gain/Loss %","Comment"
"AAPL","Apple Inc.","Jan 15, 2024","100.0","185.2","0.0","18520.0","0.0","-185.2","-18520.0","-100.0","0.0","0.0","0.0","18520.0","-18520.0","-100.0",""
```
- All values double-quoted
- 18 columns
- Date format: "MMM dd, yyyy" (e.g., "Jan 15, 2024", "Feb 01, 2024")
- Units: float format ("100.0" not "100")
- Current Price = "0.0" when offline (JStock fetches live); Gain/Loss shows -100% offline
- Companion files: `sellportfolio.csv`, `depositsummary.csv`, `dividendsummary.csv`

### sellportfolio.csv (header only if empty)
```csv
"Code","Symbol","Date","Units","Selling Price","Purchase Price","Selling Value","Purchase Value","Gain/Loss Price","Gain/Loss Value","Gain/Loss %","Broker","Clearing Fee","Stamp Duty","Net Selling Value","Net Gain/Loss Value","Net Gain/Loss %","Comment"
```

## XAUTHORITY Issue
- `~/.Xauthority` is **0 bytes** (empty) in the ubuntu-gnome-systemd_highres base image
- Correct XAUTHORITY: `/run/user/1000/gdm/Xauthority`
- Use in all xdotool/wmctrl/scrot commands:
  ```bash
  DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority xdotool ...
  ```
- Also set in `/usr/local/bin/launch-jstock`:
  ```bash
  export XAUTHORITY=/run/user/1000/gdm/Xauthority
  ```

## JStock Startup Behavior
1. JStock loads in ~25-30 seconds (Java Swing app)
2. Shows "JStock News" dialog on every launch (announces latest version)
   - Dismiss by pressing Enter (clicks the OK/Continue button)
3. Main window shows tabs: Stock Watchlist, Stock Indicator Editor, Stock Indicator Scanner, Portfolio Management
4. Default watchlist name: "My Watchlist" (shown in status bar: "[ My Watchlist ] Connected")
5. Default portfolio name: "My Portfolio"

## JStock Save Behavior (CRITICAL)
- Portfolio CSV files are **ONLY written on graceful close** (alt+F4, File > Exit)
- `pkill -f jstock.jar` does NOT trigger save → data is lost
- For warmup: use `xdotool key alt+F4` to close, wait for process to exit
- For task setup: JStock should stay running; pre-write CSV files before launch

## Pre-populating Data (Verified Working)
- Write `realtimestock.csv` to `UnitedState/watchlist/My Watchlist/` BEFORE JStock launch
- JStock reads these files on startup and displays the pre-loaded stocks
- Write `buyportfolio.csv` to `UnitedState/portfolios/My Portfolio/` BEFORE launch
- JStock loads portfolio transactions on startup (all showing -100% gain when offline)
- After warmup in post_start hook, re-write the CSV files (warmup may overwrite them)

## Tasks Summary (All Verified Interactively)

### 1. add_stock_to_watchlist
- Pre-state: 5 stocks in watchlist (AAPL, MSFT, GOOGL, AMZN, NVDA)
- Agent task: Add TSLA to "My Watchlist"
- Via UI: Click the "Stock" input field at top of watchlist → type "TSLA" → press Enter
- CRITICAL: Press Enter (not click) to select TSLA from autocomplete (clicking may select wrong ticker)
- Verified: TSLA (Tesla Inc.) appears as 6th row after Enter

### 2. record_buy_transaction
- Pre-state: Portfolio has AAPL (100), MSFT (50), NVDA (25); META NOT in portfolio
- Agent task: Add META buy transaction (50 shares @ $490, date Feb 01, 2024)
- Via UI: Portfolio Management tab → "Buy..." button at bottom → fill dialog

### 3. set_price_alert
- Pre-state: 5 stocks, all Fall Below = 0.0 (no alert)
- Agent task: Set MSFT Fall Below alert to $350
- Via UI: Click MSFT row → click Fall Below cell → press F2 to enter edit mode → type value → Tab
- NOTE: Right-click context menu does NOT have alert options; F2 key required for edit mode
- NOTE: JStock sorts watchlist alphabetically (AAPL, AMZN, GOOGL, MSFT, NVDA) in UI display
- Verified: MSFT Fall Below cell shows non-zero value with orange/yellow alert highlighting

### 4. create_new_watchlist
- Pre-state: Only "My Watchlist" exists
- Agent task: Create "Dividend Stocks" watchlist
- Via UI: Watchlist menu → "Multiple Watchlists..." → "New..." button → type name → OK
- Verified: "Dividend Stocks" appears in Watchlist menu and Multiple Watchlists dialog

### 5. export_watchlist_to_csv
- Pre-state: 5 stocks in watchlist, Desktop is empty (rm -f clears previous exports)
- Agent task: Export watchlist to ~/Desktop/watchlist_export.csv
- Via UI: File menu → "Save As..." → dialog opens pre-set to CSV → navigate to Desktop → rename to "watchlist_export" → Save/Enter
- Verified: watchlist_export.csv created on Desktop with correct CSV content
- NOTE: The Watchlist menu does NOT have export options; use File > Save As...

## Installation Notes
- JStock 1.0.7.60 includes a bundled JRE (OpenJDK 17)
- Dependencies: `wget unzip scrot wmctrl xdotool imagemagick`
- Install path: `/opt/jstock/` (extracted from zip)
- The zip contains: `jstock.sh`, `jstock.jar`, `jre/` directory

## Known Issues
- JStock shows "United States" in Country menu but stores data in `UnitedState/` directory
- When both `UnitedState/` and `United States/` dirs exist (from wrong scripts), JStock uses `UnitedState/`
- The "Welcome to Firefox" dialog may appear if Firefox launches unexpectedly
