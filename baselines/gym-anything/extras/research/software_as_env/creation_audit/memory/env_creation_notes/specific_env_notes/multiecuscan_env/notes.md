> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Multiecuscan Environment Notes

## Application Overview

Multiecuscan 5.4 is a Windows-only FCA (Fiat Chrysler Automobiles) vehicle diagnostic tool supporting Fiat, Alfa Romeo, Lancia, Chrysler, Dodge, and Jeep. It has a built-in **simulation mode** that provides simulated ECU data without requiring a physical vehicle connection, making it ideal for automated agent testing.

## Installation

### .NET Framework 3.5 Requirement

Multiecuscan uses CLR v2.0 (.NET Framework 2.0/3.5). The Windows 11 base image has .NET 3.5 "DisabledWithPayloadRemoved", meaning the DISM offline install with `/LimitAccess` will fail with error 0x800f081f.

**Solution**: Run DISM as SYSTEM (via schtasks) **without** `/LimitAccess` to allow downloading from Windows Update. This takes 5-10 minutes.

```powershell
# Must run as SYSTEM, NOT as regular user (Error 5: access denied)
$batContent = "dism /Online /Enable-Feature /FeatureName:NetFx3 /All /NoRestart > C:\Temp\dism_out.txt 2>&1`r`necho %ERRORLEVEL% > C:\Temp\dism_exit.txt"
Set-Content -Path "C:\Temp\run_dism.bat" -Value $batContent
schtasks /Create /TN "InstallDotNet35" /TR "cmd /c C:\Temp\run_dism.bat" /SC ONCE /SD 01/01/2099 /ST 00:00 /RL HIGHEST /RU SYSTEM /F
schtasks /Run /TN "InstallDotNet35"
# Poll for C:\Temp\dism_exit.txt to appear (3-10 min)
```

### .NET ngen (Native Image Generator) — CRITICAL

**After DISM installs .NET 3.5, `ngen` runs asynchronously in the background to compile native images.** Multiecuscan is a .NET CLR v2 app and will **crash immediately on launch** if ngen hasn't finished compiling the assemblies.

**Solution**: Run `ngen executeQueuedItems` after DISM (in install_multiecuscan.ps1) and again before warm-up launch (in setup_multiecuscan.ps1):

```powershell
$ngenPaths = @(
    "C:\Windows\Microsoft.NET\Framework\v2.0.50727\ngen.exe",
    "C:\Windows\Microsoft.NET\Framework64\v2.0.50727\ngen.exe"
)
foreach ($ngen in $ngenPaths) {
    if (Test-Path $ngen) {
        & $ngen executeQueuedItems 2>&1 | Out-Null
    }
}
```

**Symptom without fix**: Start-Process executes without error, but `Get-Process` shows no Multiecuscan 3 seconds later. All launch strategies (PowerShell Start-Process, direct schtasks /TR, explorer) fail identically. Manual testing may pass because enough time has elapsed for ngen to complete.

### MSI Installer

The MSI (SetupMultiecuscan54.msi, ~77MB) is downloaded from multiecuscan.net via ASP.NET postback. The download page uses hidden form fields (`__VIEWSTATE`, `__EVENTVALIDATION`) that need to be extracted with regex.

**Important**: The regex must handle `id="__VIEWSTATE"` between `name` and `value` attributes:
```powershell
# WRONG: if ($html -match 'name="__VIEWSTATE"\s+value="([^"]*)"')
# RIGHT: if ($html -match 'name="__VIEWSTATE"[^>]*value="([^"]*)"')
```

**Recommended**: Pre-include the MSI in `data/SetupMultiecuscan.msi` for reliability.

Install path: `C:\Program Files (x86)\Multiecuscan\Multiecuscan.exe`

## Session 0 Isolation (Critical)

SSH runs in Session 0, but GUI apps must display in the console session (Session 1). For .NET WinForms apps like Multiecuscan:

| Method | Result |
|--------|--------|
| Direct schtasks /TR to .exe | Fails silently |
| VBScript via wscript | Unreliable |
| **cmd batch with `start`** | **Works reliably** |

```powershell
# Working pattern — MUST use C:\Temp, NOT $env:TEMP!
# $env:TEMP resolves differently in Session 0 (SSH) vs Session 1 (interactive),
# causing schtasks /IT to fail when the batch file path is inaccessible.
$tempDir = "C:\Temp"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
$cmdFile = "$tempDir\launch_mes.cmd"
$cmdContent = "@echo off`r`nstart `"`" `"$MesExe`""
Set-Content -Path $cmdFile -Value $cmdContent
schtasks /Create /SC ONCE /IT /TR "`"$cmdFile`"" /TN "LaunchMES" /SD 01/01/2099 /ST 00:00 /RL HIGHEST /F
schtasks /Run /TN "LaunchMES"
```

**Critical**: Use `C:\Temp` (fixed path) instead of `$env:TEMP` for batch files used by schtasks `/IT`. The `/IT` flag runs the task in the interactive desktop session (Session 1), but `$env:TEMP` resolves to the SSH session's (Session 0) temp directory, which may not be accessible from Session 1.

**Note**: Always use `/SD 01/01/2099` with `/ST 00:00` to avoid "Task may not run because /ST is earlier than current time" warnings.

**Note**: Do NOT suppress stderr with `2>$null` on schtasks commands — use `2>&1` to capture errors for debugging.

## Startup Dialogs

### Disclaimer Dialog
Multiecuscan FREE shows a "Disclaimer" dialog on every launch. Close button at approximately (807, 524) at 1280x720 resolution. Also responds to ESC and Enter keys.

### OneDrive Backup Notification
Windows 11 shows "Turn On Windows Backup" popup. Dismiss by clicking "No thanks" at approximately (1136, 619). Also kill OneDrive process and disable via registry in the post_start hook.

## Simulation Mode

Enter simulation mode by:
1. Select Make (e.g., Fiat)
2. Select Model (e.g., 500 1.3 Multijet 16V)
3. Select System (e.g., Engine)
4. Select Control Module (e.g., Marelli 6F3 EOBD Diesel Injection)
5. Click "Simulate" button

Simulation provides:
- **Info tab (F2)**: ECU identification (ISO code, drawing number, HW/SW versions)
- **Errors tab (F3)**: DTC fault codes with descriptions and freeze-frame data
- **Parameters tab (F4)**: Live OBD parameters (RPM, voltage, temperature, pressure, etc.)
- **Graph tab (F5)**: Real-time parameter graphing
- **Actuators tab (F6)**: Actuator test controls
- **Adjustments tab (F7)**: ECU adjustment parameters

Status bar shows red "SIMULATION MODE!!! THE DATA IS NOT REAL!!!" when active.

## Data Files

| File | Source | Description |
|------|--------|-------------|
| `dtc_database_full.csv` | Compiled from OBD-II standards | 4000+ DTC codes with descriptions |
| `fiat_vehicle_specs.csv` | FCA technical documentation | Vehicle model specifications |
| `obd2_parameter_reference.csv` | OBD-II PID reference | Parameter names, PIDs, units, normal ranges |
| `diagnostic_procedures.txt` | Automotive diagnostic guide | Step-by-step diagnostic procedures |
| `real_obd_drive_session.csv` | Real OBD2 data logger | Actual driving session with 20+ parameters |
| `real_obd_idle_session.csv` | Real OBD2 data logger | Engine idle session data |
| `real_obd_long_session.csv` | Real OBD2 data logger | Extended monitoring session |

## Task Design

All 5 tasks use simulation mode (no physical vehicle needed):
1. **engine_fault_diagnosis**: Read ECU info, DTCs, key parameters for a Fiat 500 1.3 Multijet
2. **multi_system_scan**: Scan Engine + ABS + Airbag systems for a Fiat Ducato
3. **parameter_monitoring_export**: Monitor and export engine parameters in real-time
4. **body_computer_analysis**: Analyze Body Computer (BSI) module on a Fiat Punto
5. **complete_diagnostic_session**: Full diagnostic workflow across multiple systems

## PowerShell Gotchas

1. `2>nul` causes "FileStream was asked to open a device that was not a file" - use `2>$null` instead
2. `&` (ampersand) is a parser error in single-line commands - use `;` or multi-statement instead
3. `$_` must be escaped as `\$_` when passing through SSH
4. String quoting: use single quotes around PowerShell code in SSH commands
5. `$env:TEMP` resolves to different paths in Session 0 (SSH) vs Session 1 (interactive desktop) — always use `C:\Temp` for cross-session file sharing
6. `2>$null` on schtasks suppresses useful error messages — prefer `2>&1` to capture and log errors

## Timing

| Phase | Duration |
|-------|----------|
| Windows boot (fresh, no checkpoint) | ~2 min |
| .NET 3.5 install via Windows Update | 5-10 min |
| ngen executeQueuedItems (both hooks) | ~30-60 sec |
| MSI install (from pre-mounted file) | ~10 sec |
| Warm-up launch + kill | ~18 sec |
| Task setup (launch + dismiss dialogs) | ~45 sec |
| **Total env.reset()** | **~12-15 min** |
