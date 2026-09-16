> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Oracle Analytics Desktop — Lessons Learned

## 1. Oracle SSO Download is an Absolute Blocker

**Problem**: Oracle Analytics Desktop requires Oracle Single Sign-On (SSO) to download. There is NO public direct download link.

**Attempted workarounds (ALL FAILED)**:
- `download.oracle.com/otn/...` → 302 redirect to SSO login page
- `download.oracle.com/otn-pub/...` → redirects to `download-fail-1505220.html`
- `edelivery.oracle.com/osdc/cliauth` → HTTP 401 requiring Basic Auth
- Oracle license cookie (`oraclelicense=accept-securebackup-cookie`) → returns HTML login form, not installer
- winget / Chocolatey → OAD not available in any package repository
- Oracle Container Registry → no OAD image exists
- archive.org / third-party mirrors → nothing found
- Multiple version numbers and file name patterns → all redirect to SSO or error

**Solution**: Installer must be pre-staged in `data/` directory. User downloads manually via Oracle SSO account and places `Oracle_Analytics_Desktop_January2026_Win.exe` (1.4 GB) in the data folder. The ZIP from Oracle edelivery is `V1054835-01.zip`.

## 2. OUI Silent Install, NOT InstallShield

**Problem**: OAD uses Oracle Universal Installer (OUI), not InstallShield. InstallShield flags (`/S /v"/qn"`) don't work.

**Solution**: Use OUI silent mode with a response file:
```
<installer> -silent -responseFile C:\Windows\Temp\oad_install.rsp -nowait
```

Response file contents:
```ini
[ENGINE]
Response File Version=1.0.0.0.0

[GENERIC]
ORACLE_HOME=C:\Program Files\Oracle Analytics Desktop
INSTALL_TYPE=Complete
DECLINE_SECURITY_UPDATES=true
SECURITY_UPDATES_VIA_MYORACLESUPPORT=false
```

Exit code 0 = success. Install takes ~4.5 minutes.

## 3. Process Name is `dvdesktop`, NOT `OAD`

**Problem**: The executable and process name is `dvdesktop.exe`, not `OAD.exe` or anything with "Analytics" in it. Searching for "OAD" in process names won't find it.

**Key facts**:
- Executable: `C:\Program Files\Oracle Analytics Desktop\dvdesktop.exe`
- Process name: `dvdesktop`
- Window title: `"Oracle Analytics"` (NOT "Oracle Analytics Desktop")
- Kill command: `Get-Process dvdesktop -ErrorAction SilentlyContinue | Stop-Process -Force`

**Lesson**: Always verify the actual process name via `Get-Process` after installing — don't assume it matches the product name.

## 4. No "Region" Column in the Sample Data

**Problem**: Oracle's official sample dataset (`sample_order_lines2023.xlsx`) does NOT have a "Region" column. It has "City" but no region/state/country column.

**Actual columns** (20 total): Order Line ID, Order ID, Order Priority, Customer ID, Customer Name, Customer Segment, City, Product Category, Product Sub Category, Product Container, Product Name, Profit, Quantity Ordered, Sales, Discount, Gross Unit Price, Shipping Cost, Ship Mode, Ship Date, Order Date

**Also**: Column names use spaces ("Product Category"), not underscores ("Product_Category").

**Lesson**: Always verify actual column names from the data file before writing task descriptions.

## 5. Win32 API Works for OAD (Unlike NinjaTrader)

OAD is a standard Windows application that responds to Win32 API mouse events (SetCursorPos + mouse_event) from Session 0 via schtasks. No need for the PyAutoGUI TCP server pattern that NinjaTrader requires.

However, PyAutoGUI TCP server is still useful for interactive testing/debugging from the host.

## 6. Dataset Import Requires File Dialog Navigation

OAD does NOT accept file paths as command-line arguments (unlike some apps). The import flow is:
1. Click Create (810, 77) → menu appears
2. Click Dataset (726, 185) → "Create Dataset" dialog
3. Click "Drop file here or click to browse" area (161, 157) → Windows file dialog
4. Type full path in File Name field (340, 468)
5. Click Open (504, 498) → dataset config dialog
6. Click OK (904, 465) → dataset created

**Key insight**: Type the FULL path in the File Name field. The file dialog opens to the OAD install directory, not the user's Desktop. Navigating via the left panel is slow and unreliable.

## 7. Warm-up Launch Clears First-Run Dialogs

A single warm-up launch+kill cycle in post_start is sufficient to clear all first-run dialogs. No persistent "Welcome" or "Getting Started" dialogs were observed on subsequent launches after the warm-up.

The warm-up flow: launch via schtasks → wait 30s → run dismiss_dialogs.ps1 (Escape/Enter/Click) → kill dvdesktop → clean up scheduled tasks.

## 8. OneDrive Registry Disabling vs Checkpoint Boots

- **Fresh boot** with registry-based OneDrive disabling in pre_start: NO OneDrive dialog appears
- **Checkpoint boot** (savevm restore): OneDrive dialog DOES appear because the checkpoint was taken before the registry changes

Registry keys that prevent OneDrive:
- `HKLM:\SOFTWARE\Policies\Microsoft\Windows\OneDrive\DisableFileSyncNGSC = 1`
- Remove `HKCU:\...\Run\OneDrive` autorun entries
- Unregister `*OneDrive*` scheduled tasks
- Run `OneDriveSetup.exe /uninstall`

**Lesson**: When using `cache_level="post_start"` with savevm, OneDrive will already be disabled since the checkpoint includes the post_start state.

## 9. PyAutoGUI TCP Server Protocol Details

When using PyAutoGUI TCP server for interactive debugging:
- **Protocol**: JSON commands terminated by `\n`
- **Response keys**: `success` (bool) and `result` (dict), NOT `status`/`image`
- **Screenshots**: base64 PNG in `result.data`
- **Buffer handling**: Must read in a loop until `\n` found — large screenshots (100KB+ base64) exceed single `recv(65536)` call
- **Port**: Guest port 5555, mapped to dynamic host port accessible via `env._runner._pyautogui_port`

## 10. Timing Considerations

| Phase | Duration | Notes |
|-------|----------|-------|
| VM boot | ~3s | KVM-accelerated, Windows desktop ready quickly |
| Data mount (1.4GB installer) | ~30s | Large file copy over SSH |
| pre_start (install) | ~4.5 min | OUI silent install + OneDrive/WU cleanup |
| post_start (warm-up) | ~52s | Data copy + warm-up launch + dialog dismiss |
| pre_task (launch OAD) | ~50s | Launch via schtasks + 25s wait + dialog dismiss |
| **Total fresh boot** | **~8 min** | |
| **With post_start cache** | **~50s** | Only pre_task runs |
