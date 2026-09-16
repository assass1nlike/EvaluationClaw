> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Oracle Analytics Desktop Environment Notes

## Application Overview
- **Name**: Oracle Analytics Desktop (OAD), formerly Data Visualization Desktop (DVD)
- **Type**: Windows-only desktop data visualization/analytics tool
- **Version**: January 2026 Update
- **Vendor**: Oracle
- **No Linux version** — Windows and macOS only

## Installation (VERIFIED)
- **Installer**: `Oracle_Analytics_Desktop_January2026_Win.exe` (1.4 GB)
- **Source**: Oracle edelivery (`V1054835-01.zip`), requires Oracle SSO login
- **Silent install**: OUI with response file: `-silent -responseFile <rsp> -nowait`
- **Exit code**: 0 (success)
- **Install time**: ~4.5 minutes
- **Install path**: `C:\Program Files\Oracle Analytics Desktop\`
- **Executable**: `C:\Program Files\Oracle Analytics Desktop\dvdesktop.exe`
- **Process name**: `dvdesktop`
- **Window title**: "Oracle Analytics"

## Key Application Features
- Create datasets from CSV, XLSX, TXT files (max 250 MB, max 250 columns per sheet)
- Visualization types: Bar, Pie, Line, Combo, Table, Treemap, Scatter, and more
- Calculated columns with formula expressions
- Dashboard filters
- Workbook saved as `.dva` files
- No login required to use (offline/standalone)

## Data
- **Primary dataset**: Oracle's official tutorial sample `sample_order_lines2023.xlsx`
  - Source: https://docs.oracle.com/en/cloud/paas/analytics-cloud/tutorial-create-first-visualization/files/sample_order_lines2023.xlsx
  - 9000 rows, 20 columns (DV Orders sheet)
  - Columns: Order Line ID, Order ID, Order Priority, Customer ID, Customer Name, Customer Segment, City, Product Category, Product Sub Category, Product Container, Product Name, Profit, Quantity Ordered, Sales, Discount, Gross Unit Price, Shipping Cost, Ship Mode, Ship Date, Order Date
- **CSV version**: `order_lines.csv` — same data converted to CSV format

## OAD Home Screen UI Coordinates (1280x720, verified via visual_grounding)

**Top Navigation:**
- Hamburger menu: (54, 77)
- Create button: (810, 77)
- Home icon: (910, 77)
- Help icon: (954, 77)

**Create Menu (after clicking Create):**
- Workbook: (650, 185)
- Dataset: (726, 185)
- Data Flow: (800, 185)
- Sequence: (652, 260)
- Connection: (726, 260)

**Search Bar:** (505, 127)

**What's New Cards:**
- Download Samples: (255, 314)
- Connect to Oracle Autonomous Data Warehouse: (497, 314)
- Connect to Your Data: (740, 314)

**Window Controls:** Minimize (863,40), Maximize (909,40), Close (955,40)

## Dataset Import Flow (verified)
1. Create > Dataset → "Create Dataset" dialog
2. "Drop file here or click to browse" area at (161, 157) → file dialog
3. File Name field at (340, 468), type full path
4. Open button at (504, 498)
5. Dataset config dialog: Name field (340, 155), OK (904, 465), Cancel (838, 465)

## First-Run Behavior
- Warm-up launch in post_start clears first-run dialogs
- No persistent first-run dialogs observed after warm-up
- OneDrive dialog prevented by registry disabling in pre_start

## OneDrive "Turn On Windows Backup" Dialog
- Appears from checkpoint boots (not fresh boots with registry disabling)
- Coordinates at 1280x720:
  - "No thanks" button: **(1167, 627)**
  - X close button: **(1237, 392)**
- **Fix**: Registry-based OneDrive disabling in pre_start prevents this dialog on fresh boots

## Desktop Icon Coordinates (1280x720, verified via visual_grounding)
- Recycle Bin: (37, 37)
- Microsoft Edge: (37, 155)
- Shared folder: (37, 257)
- setup.ps1: (37, 359)
- OracleAnalyticsData folder: (37, 470)

## GUI Automation
- **Win32 API** (SetCursorPos + mouse_event) works for OAD (standard Windows app)
- **PyAutoGUI TCP server** also available as fallback
- **Resolution**: 1280x720 (QEMU virtio-vga)
- OAD takes 20-30 seconds to fully load (Java-based)

## Process Detection
- Process name: `dvdesktop`
- Use: `Get-Process dvdesktop -ErrorAction SilentlyContinue`
- Fallback: `Get-Process | Where-Object { $_.Path -match "Oracle.*Analytics" }`

## Timing
- Total env setup: ~458 seconds (7.6 minutes)
  - Pre-start (install + system setup): ~406 seconds
  - Post-start (data copy + warm-up): ~52 seconds
- Pre-task (launch OAD): ~50 seconds

## Testing Pattern
```python
from gym_anything.api import from_config
env = from_config("benchmarks/cua_world/environments/oracle_analytics_desktop_env", task_id="create_bar_chart")
obs = env.reset(seed=42, use_cache=True, cache_level="post_start", use_savevm=True)
# SSH: env._runner.ssh_port, VNC: env._runner.vnc_port
# Screenshot: env._runner.capture_screenshot('/tmp/screenshot.png')
```
