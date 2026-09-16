> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Windows VM Environment Setup — OS-Level Lessons Learned

These notes cover **Windows-specific OS patterns** discovered while setting up GUI applications in Windows QEMU VMs via SSH. They apply to setting up **any** software on Windows, not just Excel/Office.

---

## 1. Session 0 Isolation (CRITICAL — Affects ALL GUI Apps)

SSH sessions on Windows run in **Session 0**, a non-interactive session that **cannot display GUI windows**. Any GUI app launched directly from SSH (`Start-Process`, `Invoke-Item`, etc.) will start but remain **invisible** — it runs in Session 0, not on the user's desktop.

**This means**: You CANNOT just run `Start-Process "C:\Program Files\SomeApp\app.exe"` from SSH and expect to see it on the desktop.

**Solution: Use `schtasks` with the `/IT` (Interactive) flag** to run commands in the interactive desktop session:

```powershell
schtasks /Create /TN "TaskName" /TR "command here" /SC ONCE /ST 00:00 /RL HIGHEST /IT /F
schtasks /Run /TN "TaskName"
Start-Sleep -Seconds 12  # Wait for app to start
schtasks /Delete /TN "TaskName" /F  # Clean up
```

This pattern is needed for:
- Launching any GUI application
- Running scripts that interact with the desktop (mouse clicks, keystrokes)
- Any automation that needs to see or manipulate GUI windows

## 2. schtasks Quoting Issues with Spaces in Paths

`schtasks /TR` has **severe quoting limitations** when the command path contains spaces (e.g., `C:\Program Files\...`). Nested double-quotes often get mangled or misinterpreted.

**Solution: Create a `.cmd` batch file** and have schtasks run that instead:

```powershell
$launchScript = "C:\Windows\Temp\launch_app.cmd"
$batchContent = "@echo off`r`nstart `"`" `"C:\Program Files\App\app.exe`" `"$filePath`""
[System.IO.File]::WriteAllText($launchScript, $batchContent)

schtasks /Create /TN "LaunchApp" /TR "cmd /c $launchScript" /SC ONCE /ST 00:00 /RL HIGHEST /IT /F
schtasks /Run /TN "LaunchApp"
```

This avoids all quoting headaches — the batch file handles the complex paths.

## 3. PowerShell Strict Mode + Native Commands (schtasks, msiexec, etc.)

When `$ErrorActionPreference = "Stop"` is set, **native commands** (like `schtasks`, `msiexec`, `net`, etc.) that write anything to stderr will cause **terminating errors** in PowerShell — even if the command succeeded. This is a PowerShell gotcha where stderr output ≠ failure for native commands.

Even `2>&1 | Out-Null` does NOT prevent this under strict mode.

**Solution**: Temporarily relax error handling for native commands:

```powershell
$prevEAP = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    schtasks /Create ... 2>$null
    schtasks /Run ... 2>$null
} finally {
    $ErrorActionPreference = $prevEAP
}
```

**Key**: Use `2>$null` (not `2>&1 | Out-Null`) — it's the only safe option under strict mode.

## 4. GUI Automation from SSH via Win32 API

Since SSH can't directly interact with the desktop GUI, use **schtasks-launched PowerShell scripts** that:
1. Run in the interactive session (via `schtasks /IT`)
2. Use `Add-Type` to import Win32 `user32.dll` functions
3. Use `SetCursorPos` + `mouse_event` for mouse clicks
4. Use `[System.Windows.Forms.SendKeys]::SendWait()` for keyboard input
5. Use `SetForegroundWindow` to bring target windows to focus

```powershell
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class Win32Mouse {
    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")]
    public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    public const uint MOUSEEVENTF_LEFTUP = 0x0004;
}
"@

# Click at specific coordinates
function Click-At {
    param([int]$X, [int]$Y)
    [Win32Mouse]::SetCursorPos($X, $Y)
    Start-Sleep -Milliseconds 150
    [Win32Mouse]::mouse_event([Win32Mouse]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 50
    [Win32Mouse]::mouse_event([Win32Mouse]::MOUSEEVENTF_LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
}
```

**CRITICAL Warning**: Do NOT reference `System.Windows.Forms` or `System.Drawing` inside `Add-Type -TypeDefinition` C# code — the assembly references won't be found and compilation will fail with `InvalidOperation`. Keep Win32 P/Invoke in a separate `Add-Type -TypeDefinition` block and load .NET assemblies separately with `Add-Type -AssemblyName`:

```powershell
# WRONG — will fail:
Add-Type -TypeDefinition @"
using System.Windows.Forms;
public class Helper { public static void Send() { SendKeys.SendWait("{ESCAPE}"); } }
"@

# RIGHT — use separate calls:
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{ESCAPE}")
```

## 5. OneDrive Popup Suppression (Blocks Screen on Fresh Boots)

OneDrive shows a **"Turn On Windows Backup"** popup that blocks screen interaction on fresh Windows 11 VMs. Multiple approaches needed to fully suppress it:

```powershell
# Kill processes
Get-Process OneDrive -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process OneDriveSetup -ErrorAction SilentlyContinue | Stop-Process -Force

# Remove from startup registry
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "OneDrive" -ErrorAction SilentlyContinue

# Disable via Group Policy
$policyPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\OneDrive"
if (-not (Test-Path $policyPath)) { New-Item -Path $policyPath -Force | Out-Null }
Set-ItemProperty -Path $policyPath -Name "DisableFileSyncNGSC" -Value 1

# Uninstall with timeout — CRITICAL: Do NOT use Start-Process -Wait
$oneDriveSetup = "$env:SystemRoot\SysWOW64\OneDriveSetup.exe"
if (-not (Test-Path $oneDriveSetup)) {
    $oneDriveSetup = "$env:SystemRoot\System32\OneDriveSetup.exe"
}
if (Test-Path $oneDriveSetup) {
    $proc = Start-Process $oneDriveSetup -ArgumentList "/uninstall" -PassThru
    $proc.WaitForExit(30000)  # 30-second timeout
}

# Disable Windows Backup notifications
$backupPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\CloudContent"
if (-not (Test-Path $backupPath)) { New-Item -Path $backupPath -Force | Out-Null }
Set-ItemProperty -Path $backupPath -Name "DisableWindowsConsumerFeatures" -Value 1
```

**Critical**: `Start-Process -Wait` for OneDrive uninstall can **hang for 10+ minutes**. Always use `-PassThru` with `WaitForExit(timeout)`.

## 6. Application First-Run Dialogs (General Pattern)

Most Windows applications show first-run dialogs (EULAs, sign-in, privacy, etc.) on initial launch. These often **cannot be suppressed by registry keys alone**.

**General solution — Warm-up launch in post_start hook**:
1. Launch the app once via schtasks in the interactive session
2. Wait for it to fully start (~10-15 seconds)
3. Kill it immediately (`Stop-Process -Force`)
4. On subsequent launches, the first-run cycle is complete and the app shows simpler/dismissable dialogs

```powershell
# Generic warm-up pattern for any GUI app
$warmupScript = "C:\Windows\Temp\warmup_app.cmd"
$warmupContent = "@echo off`r`nstart `"`" `"$appExePath`""
[System.IO.File]::WriteAllText($warmupScript, $warmupContent)

$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
schtasks /Create /TN "WarmupApp" /TR "cmd /c $warmupScript" /SC ONCE /ST 00:00 /RL HIGHEST /IT /F 2>$null
schtasks /Run /TN "WarmupApp" 2>$null
Start-Sleep -Seconds 15
Get-Process $processName -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3
schtasks /Delete /TN "WarmupApp" /F 2>$null
Remove-Item $warmupScript -Force -ErrorAction SilentlyContinue
$ErrorActionPreference = $prevEAP
```

**Why this works**: Most apps write first-run state to registry or AppData after initial launch. Even if the app was force-killed, the first-run markers are already written.

## 7. PyAutoGUI Server Behavior on Windows

- The PyAutoGUI TCP server **fails to start on the first boot** (3 retries fail over ~120s). This is expected because the desktop environment isn't fully ready during fresh boot.
- After a `loadvm` checkpoint restore, the server starts successfully on the first attempt.
- The server must run via `schtasks /IT` in the interactive session (Session 0 can't capture screenshots).
- Framework handles retries automatically — no action needed, just be aware of the ~2 min delay on first boot.

## 8. Windows Desktop Readiness

After boot or loadvm, Windows needs time for:
- Explorer shell to start
- Desktop icons to appear
- System tray to populate
- Background services to initialize

The framework waits for desktop readiness, but GUI apps launched too early may behave unexpectedly. Add `Start-Sleep` delays after schtasks launches (12-15 seconds for most apps).

## 9. Software Installation Patterns on Windows VMs

### Silent installers (MSI/EXE)
```powershell
# MSI (most reliable)
Start-Process msiexec.exe -ArgumentList "/i `"$msiPath`" /qn /norestart" -Wait

# EXE with silent flag (varies by installer)
Start-Process $exePath -ArgumentList "/S", "/silent", "/verysilent" -Wait  # try common flags

# Chocolatey (if available — easiest)
choco install $packageName -y --no-progress
```

### Download + install pattern
```powershell
# Download to temp
$url = "https://example.com/installer.exe"
$dest = "C:\Windows\Temp\installer.exe"
Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing

# Install silently
Start-Process $dest -ArgumentList "/S" -Wait
Remove-Item $dest -Force
```

### Key notes:
- Always use `/qn` (quiet, no UI) for MSI installs
- Check if the installer supports `/S`, `/silent`, `/verysilent`, or `/quiet` flags
- Use `-Wait` for installers (they finish and exit, unlike OneDrive uninstall)
- `C:\Windows\Temp\` is writable and a good staging location
- `net` must be enabled in env.json if downloading installers

## 10. Registry Manipulation Patterns

```powershell
# Create registry path if it doesn't exist (REQUIRED before setting values)
$regPath = "HKCU:\Software\SomeApp\Settings"
if (-not (Test-Path $regPath)) {
    New-Item -Path $regPath -Force | Out-Null
}
Set-ItemProperty -Path $regPath -Name "SettingName" -Value 1 -Type DWord -Force

# Common registry locations:
# HKCU:\Software\                    — per-user app settings
# HKLM:\SOFTWARE\                    — machine-wide app settings
# HKLM:\SOFTWARE\Policies\           — group policy overrides (strongest)
# HKCU:\Software\Microsoft\Windows\CurrentVersion\Run  — startup programs
```

**Tip**: Group Policy paths (`HKLM:\SOFTWARE\Policies\...`) override user settings and are the most reliable way to enforce configuration.

## 11. Common Windows Popups to Suppress

These popups commonly appear on fresh Windows 11 VMs and can block automation:

| Popup | Solution |
|-------|----------|
| OneDrive "Turn On Backup" | Kill process + uninstall (see #5) |
| Windows Update notifications | `HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate` |
| "Get Windows tips" | `HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager\SubscribedContent-338389Enabled` = 0 |
| Microsoft Edge first-run | Kill msedge process, set `HKLM:\SOFTWARE\Policies\Microsoft\Edge\HideFirstRunExperience` = 1 |
| Windows Security alerts | Group Policy or Security Center registry keys |
| Cortana/Search highlights | Registry keys under ContentDeliveryManager |

## 12. Timing Guidelines

| Operation | Typical Time | Notes |
|-----------|-------------|-------|
| App launch via schtasks | 10-15s | Varies by app size |
| Dialog dismiss script | 12-18s | Multiple Escape + clicks with waits |
| OneDrive uninstall | Up to 30s | With timeout, can hang without |
| App warm-up cycle | 15s launch + 3s kill | One-time in post_start |
| Total post_start | 100-120s | Registry + OneDrive + warm-up |
| Total pre_task | 30-35s | Kill + launch + dismiss |
| Fresh checkpoint build | 5-15 min | Depends on installation size |
| loadvm restore | 10-20s | Depends on VM memory size |

---

## Summary: Recommended Architecture for Any Windows GUI App

```
post_start hook (setup_app.ps1):
  1. Set registry keys to suppress OS-level popups and first-run dialogs
  2. Kill interfering OS processes (OneDrive, Edge, etc.)
  3. Warm-up launch of the app (complete first-run cycle)
  4. Kill the app
  5. Minimize any leftover terminal/console windows

pre_task hook (setup_task.ps1):
  1. Kill any existing app instances
  2. Copy/prepare task-specific data files
  3. Launch app with data file via schtasks + batch file
  4. Wait for app to fully load (10-15s)
  5. Run dismiss_dialogs.ps1 via schtasks to handle remaining popups
  6. Verify app is running (Get-Process check)
```

Key principle: **Everything that touches the GUI must go through `schtasks /IT`**. SSH (Session 0) is only for registry changes, file operations, and process management.
