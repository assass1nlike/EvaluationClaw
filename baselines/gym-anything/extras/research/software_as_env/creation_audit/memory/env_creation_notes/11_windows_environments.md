# Windows Environments Guide

Patterns and lessons learned from Windows-based gym_anything environments (Power BI, NinjaTrader, Office 2010, Visual Studio 2022, Copper POS, Vital Recorder, Blue Sky Plan, Oracle Analytics).

> **See also:** `10_cross_cutting_patterns.md` patterns 28-30 for: `schtasks /IT` requirement, Win32 vs PyAutoGUI automation, PowerShell strict mode.

---

## Architecture: Session 0 Isolation

**The fundamental constraint:** SSH in Windows runs in Session 0 (the service session). Session 0 is isolated — GUI windows created there are invisible.

```
SSH → Session 0 (no display) → GUI app → invisible window
SSH → schtasks /IT → Session 1 (user desktop) → GUI app → visible in VNC ✓
```

**This affects everything:** installs, warm-ups, task setup, automation.

---

## Installation Patterns

### MSI Silent Install
```powershell
# Standard silent install
msiexec /i "App.msi" /qn /norestart

# With logging (useful for debugging)
msiexec /i "App.msi" /qn /norestart /log "C:\install.log"

# Exit code 3010 = "reboot recommended" — NOT an error, app works without reboot
$result = Start-Process msiexec -ArgumentList "/i App.msi /qn /norestart" -Wait -PassThru
if ($result.ExitCode -eq 0 -or $result.ExitCode -eq 3010) {
    Write-Host "Install succeeded"
}
```

### Office 2010 (MSI, Not Click-to-Run)
- **Office 2010 Starter (Click-to-Run) FAILS on Windows 11** — App-V 4.x vs Win11 incompatibility
- **Office 365 via ODT is UNUSABLE** — non-dismissable "Sign in to get started" dialog
- **Office 2010 Pro Plus (MSI) works** — no login, no activation required
- ISO source: `archive.org/details/office2010nokeyneeded_201908` (731MB)
- Silent install: `setup.exe /config office_config.xml`
- Paths: `C:\Program Files (x86)\Microsoft Office\Office14\{WINWORD,EXCEL}.EXE`

### Suppressing Startup Apps (OneDrive, Teams, etc.)
```powershell
# Uninstall OneDrive without hanging
$proc = Start-Process "$env:SystemRoot\SysWOW64\OneDriveSetup.exe" -ArgumentList "/uninstall" -PassThru
$proc.WaitForExit(30000)  # 30s timeout — NOT -Wait (hangs!)

# Disable startup entries
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v OneDrive /f 2>$null
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v Teams /f 2>$null
```

---

## Launching GUI Apps from SSH

### The schtasks Pattern
```powershell
# Create a scheduled task to run in the interactive session
$time = (Get-Date).AddMinutes(1).ToString("HH:mm")
$action = "C:\Program Files\App\app.exe"
$taskName = "LaunchApp_Warmup"

# Remove any existing task with this name
schtasks /Delete /TN $taskName /F 2>$null

# Create task scheduled 1 minute from now
$ErrorActionPreference = "Continue"  # Prevent strict mode from failing on schtasks stderr
schtasks /Create /SC ONCE /IT /TR "`"$action`"" /TN $taskName /ST $time /F 2>$null
$ErrorActionPreference = "Stop"

# Wait for it to run
Start-Sleep -Seconds 70

# Clean up
schtasks /Delete /TN $taskName /F 2>$null
```

### Detecting When GUI App Is Ready
```powershell
# Wait for process to appear
$maxWait = 60
$elapsed = 0
while ($elapsed -lt $maxWait) {
    $proc = Get-Process -Name "AppName" -ErrorAction SilentlyContinue
    if ($proc) { break }
    Start-Sleep -Seconds 2
    $elapsed += 2
}

# Wait for window to appear (window title detection)
$wshell = New-Object -ComObject WScript.Shell
for ($i = 0; $i -lt 30; $i++) {
    $windows = [System.Diagnostics.Process]::GetProcessesByName("AppName")
    if ($windows | Where-Object { $_.MainWindowTitle -ne "" }) { break }
    Start-Sleep -Seconds 2
}
```

---

## GUI Automation Methods (Priority Order)

### 1. VNC Clicks (Simplest)
```python
from gym_anything.runtime.runners.vnc_utils import VNCConnection
vnc = VNCConnection("localhost", vnc_port, password="password")
vnc.connect()
vnc.mouse_move(x, y)
vnc.mouse_click()
screenshot_bytes = vnc.capture_screenshot()
```

### 2. Win32 API (SetCursorPos + mouse_event)
```powershell
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(int dwFlags, int dx, int dy, int cButtons, int dwExtraInfo);
    public const int MOUSEEVENTF_LEFTDOWN = 0x02;
    public const int MOUSEEVENTF_LEFTUP = 0x04;
    public static void Click(int x, int y) {
        SetCursorPos(x, y);
        System.Threading.Thread.Sleep(100);
        mouse_event(MOUSEEVENTF_LEFTDOWN, x, y, 0, 0);
        System.Threading.Thread.Sleep(50);
        mouse_event(MOUSEEVENTF_LEFTUP, x, y, 0, 0);
    }
}
"@
[Win32]::Click(500, 300)
```

**Does NOT work for:** NinjaTrader, Copper POS (NCH Software). Use PyAutoGUI fallback.

### 3. PyAutoGUI TCP Server (Most Reliable Fallback)
Deploy a Python socket server on the Windows VM in `post_start`:
```powershell
# start_pyautogui_server.py (deployed to VM)
python3 start_pyautogui_server.py &

# In task_utils.ps1 — helper functions
function PyAutoGUI-Click($x, $y) {
    $cmd = @{action="click"; x=$x; y=$y} | ConvertTo-Json
    # Send to TCP server on port 5555
    ...
}
```

### 4. SendKeys (Last Resort)
```powershell
$wshell = New-Object -ComObject WScript.Shell
$wshell.AppActivate("Window Title")
Start-Sleep -Milliseconds 200
$wshell.SendKeys("{ENTER}")
$wshell.SendKeys("text to type")
$wshell.SendKeys("%{F4}")  # Alt+F4
```

---

## Add-Type Gotcha: Separate Definitions

Win32 P/Invoke types and .NET framework types must be in **separate `Add-Type` calls**:

```powershell
# WRONG — mixing P/Invoke with Add-Type -AssemblyName in same Add-Type
Add-Type -TypeDefinition @"...Win32 P/Invoke..."@
Add-Type -AssemblyName "System.Windows.Forms"  # This causes conflicts

# RIGHT — separate calls
Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public class Win32 { ... }
"@

Add-Type -AssemblyName "System.Windows.Forms"
```

---

## VNC Resolution

- Standard resolution: **1280x720** (matches VLM output exactly — no scaling needed)
- Some envs: 1920x1080 (check env.json `resolution` field)
- VNC password: Always `"password"` (set in env.json `vnc.password`)

---

## First-Run Dialog Suppression

### Office 365 Warm-Up Pattern
Office 365 shows a non-dismissable "Sign in to get started" dialog on first launch. Fix with warm-up in `post_start`:
```powershell
# Schedule warm-up via schtasks
# On first launch, the dialog appears — dismiss it programmatically
# On subsequent launches (tasks), the dialog doesn't appear
```

### Document Recovery Panel
After Office is force-killed (normal in gym_anything task resets), it shows "Document Recovery" on next launch. The Close button is at approximately **(216, 628)** on 1280x720.

### Registry-Based Suppression
```powershell
# Suppress first-run wizards via registry
reg add "HKCU\Software\Microsoft\Office\16.0\Common\General" /v "ShownFileFmtPrompt" /t REG_DWORD /d 1 /f
reg add "HKCU\Software\Microsoft\Office\16.0\Common\PTWatson" /v "PTWOptIn" /t REG_DWORD /d 0 /f
```

---

## Environment-Specific Quick Reference

| Environment | Install method | Key gotcha |
|------------|---------------|------------|
| Power BI Desktop | `PBIDesktopSetup_x64.exe -quiet -norestart ACCEPT_EULA=1` | First-run dialogs only appear on FIRST launch from checkpoint |
| NinjaTrader 8 | `msiexec /qn /i NinjaTrader.Install.V8.msi` | Win32 clicks don't work — use PyAutoGUI TCP server |
| Office 2010 Pro | `setup.exe /config office_config.xml` | Exit code 3010 = OK, not error |
| Visual Studio 2022 | `vs_BuildTools.exe --quiet --norestart` | Must install via workloads, not individual components |
| Copper POS | Web stub installer, must use PyAutoGUI | Win32 AND VNC clicks don't work |

---

## See Also

- `10_cross_cutting_patterns.md` — patterns 17, 28, 29, 30 for setsid, schtasks, Win32 vs PyAutoGUI, PowerShell strict mode
- `specific_env_notes/power_bi_desktop_env/` — Power BI first-run dialogs, canvas safe zones
- `specific_env_notes/ninja_trader_env/ninja_trader_lessons_learned.md` — PyAutoGUI server setup
- `specific_env_notes/microsoft_excel_2010_env/` — Office 2010 install patterns
- `specific_env_notes/copper_point_of_sale_env/` — NCH installer automation
