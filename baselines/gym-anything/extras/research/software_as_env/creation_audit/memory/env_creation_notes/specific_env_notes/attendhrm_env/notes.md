> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# AttendHRM Environment Notes

Status: FULLY VERIFIED 2026-02-24

## Application Info

- **App**: AttendHRM Attendance Lite (Demo) — Windows-only desktop HR/attendance management app
- **Developer**: Lenvica Computer Solutions
- **Installer**: ~287MB Inno Setup from `https://www.lenvica.com/download/AttendHRM-Attendance-Lite-Setup.exe`
- **Database**: Firebird 2.0 (bundled, auto-starts as Windows service `FirebirdServerDefaultInstance`)
- **Demo data**: 50 employees, ~5 departments, real attendance punches

## Install Path (CRITICAL)

AttendHRM installs to `C:\Program Files (x86)\Attend HRM\Bin\Attend.exe` — NOT `Attend.exe` directly in the Attend HRM folder. The `Bin\` subdirectory is required.

```powershell
$candidates = @(
    "C:\Program Files (x86)\Attend HRM\Bin\Attend.exe",   # Actual path (verified)
    "C:\Program Files (x86)\Attend HRM\Attend.exe",
    ...
)
```

## Installer [Run] Section Blocks Silent Install (CRITICAL)

The AttendHRM Inno Setup installer has a [Run] section that launches `Attend.exe` at the end of installation and waits for it to exit (no `nowait` flag). In a headless Session 0 environment, Attend.exe never exits on its own, causing `Start-Process ... -Wait` to hang indefinitely.

**Fix**: Use a background PowerShell job to kill `Attend.exe` every 5 seconds while the installer is running:
```powershell
$killJob = Start-Job -ScriptBlock {
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Seconds 5
        Stop-Process -Name "Attend" -Force -ErrorAction SilentlyContinue
    }
}
try {
    $installResult = Start-Process $installerPath -ArgumentList "/VERYSILENT"... -Wait -PassThru
} finally {
    Stop-Job $killJob -ErrorAction SilentlyContinue
    Remove-Job $killJob -Force -ErrorAction SilentlyContinue
}
```
Without this fix, the install hangs until manually killed (verified: 30+ minute hang).

## Download (CRITICAL)

Use `curl.exe` for the installer download — `Invoke-WebRequest` stalls on large files (287MB):

```powershell
$curlArgs = @("--retry", "3", "--retry-delay", "5", "-L", "--max-time", "600",
              "-o", $installerPath, $url)
Start-Process "curl.exe" -ArgumentList $curlArgs -Wait -PassThru
```

## Launching AttendHRM (CRITICAL)

**MUST use PyAutoGUI double-click on desktop icon** — schtasks /IT approach launches the process in background (Session 1) but the window does NOT come to the foreground due to Windows security restrictions. With schtasks, the terminal window covers the login dialog.

**Correct approach**: Double-click the AttendHRM desktop shortcut via PyAutoGUI:
```powershell
# Desktop icon at (30, 469) — visible to left of terminal (terminal starts at x≈52)
Invoke-PyAutoGUICommand -Command @{action="doubleClick"; x=30; y=469}
```

This launches Attend.exe AND brings its window to the foreground.

## Login Flow (CRITICAL)

After launch, the sequence is:
1. **CEF error dialog** appears: "CEF binaries missing!" — title bar X at approximately (737, 13). Click to dismiss. If no CEF dialog, click is harmless.
2. **Login dialog** appears centered (~420-860 x, ~140-520 y): username "admin" pre-filled
3. Click password field at **(665, 381)**, type "admin"
4. Click Login button at **(618, 491)**
5. **Demo warning dialog**: "You have chosen Database as 'Demo'" — OK button at **(639, 371)**
6. **Dashboard** loads

## First-Run Dialogs

On FIRST launch after install:
1. **Windows Firewall**: "Allow AttendHRMAPI" -- now handled via programmatic firewall rules (`netsh advfirewall`) in post_start. No UI click needed.
2. **Employer Details**: Company Name field **(700, 303)**, City **(700, 330)**, Country **(700, 357)**, Save & Continue **(791, 387)** -- now handled in Login-AttendHRM function (task_utils.ps1) so every login handles it.

## Critical Encoding Issue (FIXED 2026-03-16)

PowerShell scripts containing UTF-8 em-dash characters (U+2014) fail to parse on Windows 11 when copied via SCP. The entire script fails silently with exit code 1. All em-dashes must be replaced with ASCII `--`. This affects comments and string literals in .ps1 files.

## Menu Structure (Verified)

Menu bar: **File | View | Modules | Window | Help**

Modules submenu items and coordinates (1280x720):
- General (148, 55)
- **Employer** (152, 84) → Department (307, 144), Location (297, 114), etc.
- **Employee** (153, 114) → Employee list (299, 144), Import (293, 565)
- Roster (144, 144)
- Attendance (158, 174)
- Leave (143, 204)
- Salary (144, 234)
- Income Tax (159, 264)
- Devices (148, 294)
- Administration (169, 324)
- **Reports** (147, 354) → Attendance Reports (329, 474)
- Settings (150, 384)

## Confirm Dialog

When navigating FROM an open module screen TO another module, a "Confirm" dialog appears:
> "All open screens should be closed. Do you want to continue?"

Buttons: **Yes (558, 371)**, No (639, 371), Cancel (720, 371)

**NOT triggered** when navigating from Dashboard (fresh login). Setup scripts navigate from Dashboard so `Handle-ConfirmDialog` is not needed in setup scripts.

## Task Screens

| Task | Navigation | Start State |
|---|---|---|
| `add_department` | Modules > Employer > Department | Department list (chart + table with ACC/ADM/IT) |
| `add_employee` | Modules > Employee > Employee | Active Employees list (50 employees, 7 columns) |
| `edit_employee_designation` | Modules > Employee > Employee | Same as add_employee |
| `generate_attendance_report` | Modules > Reports > Attendance Reports | Report list (26+ types incl. Attendance Register - Monthly) |
| `import_employees` | Modules > Employee > Import | Employee Import Wizard (format selection step) |

## Process Architecture

AttendHRM runs as 7 processes:
- 1 main `Attend.exe` process (Session 1, interactive)
- 6 child processes (various components)

`Stop-AttendHRM` kills the main process and all children via `Get-Process -Name Attend | Stop-Process -Force`.

## Verifiers

Verifier scripts in `tasks/*/verifier.py` check task completion programmatically. All use `verify_*` function names matching the `task.json` `spec.program` field.

## Known Issues / Gotchas

1. **CEF binaries missing**: Non-fatal error dialog on every launch. CEF is not needed for attendance functionality — app works fine without it. Just dismiss the dialog.
2. **Multiple processes**: AttendHRM spawns 7 Attend.exe processes. `tasklist` shows all of them.
3. **Session 0 isolation**: SSH runs in Session 0; GUI in Session 1. Win32 `SetForegroundWindow` from Session 0 doesn't work on Session 1 windows. Use PyAutoGUI double-click on desktop icon instead.
4. **Demo database**: Must use Demo database — it has pre-populated employees and data. Don't switch to Live.
5. **Firebird service**: Auto-starts after install. May need 60s to be ready on first boot.
