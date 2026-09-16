> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# bcWebCam Environment (bcwebcam_env) — FULLY VERIFIED 2026-02-23

## Overview
- **Application**: bcWebCam v3.0.4 by QualitySoft — Windows-only freeware barcode/QR code scanner
- **Base**: `windows-11` preset (4 CPU, 8GB RAM, 1280x720)
- **Download URL**: `https://bcwebcam.de/wp-content/uploads/area-en/bcwebcam_en.zip`
- **Install**: MSI silent install via `msiexec /i bcWebCamSetup.en.msi /qn /norestart` (exit code 3010 = reboot recommended, not error)
- **Install path**: `C:\Program Files\bcWebCam\bcWebCam.exe`

## Architecture
- **No physical webcam**: VM has no camera device; bcWebCam shows "No compatible WebCam device driver" error on launch
- **Tasks are configuration-focused**: All 5 tasks modify bcWebCam settings via Options/Barcode Options dialogs (no scanning required)
- **PyAutoGUI TCP server**: GUI automation via TCP port 5555 for dialog dismissal
- **schtasks /IT pattern**: Required to launch bcWebCam in interactive Session 1 from SSH Session 0

## CRITICAL Bugs Found & Fixed

### 1. PowerShell `$Host` variable conflict (FATAL)
- **Bug**: `Invoke-PyAutoGUICommand` function in `task_utils.ps1` used `$Host` as parameter name
- **Effect**: PowerShell's `$Host` is read-only automatic variable; function ALWAYS fails with "Cannot overwrite variable Host because it is read-only or constant"
- **Fix**: Renamed parameter from `$Host` to `$Server`
- **Impact**: ALL dialog dismissal via `Invoke-PyAutoGUICommand` was silently failing (errors swallowed by try/catch)

### 2. Dialog Z-order / window focus (clicks miss target)
- **Bug**: PyAutoGUI console window covers bcWebCam dialogs; clicks at dialog coordinates hit console instead
- **Effect**: `Dismiss-BcWebCamDialogs` clicks land on wrong window, dialogs remain visible
- **Fix**: Added Alt+Tab cycling before each Enter press to bring bcWebCam dialogs to foreground
- **Pattern**: `Alt+Tab → Enter → Alt+Tab → Enter → coordinate clicks as fallback`

### 3. pip stderr kills PowerShell script
- **Bug**: `pip install` outputs `[notice]` to stderr; `$ErrorActionPreference = "Stop"` treats this as fatal
- **Fix**: Wrap pip install with `$ErrorActionPreference = "Continue"` and `2>&1 | ForEach-Object`

### 4. MSI exit code 3010
- **Bug**: `msiexec /i ... /qn /norestart` returns exit code 3010 (reboot recommended)
- **Effect**: PowerShell treats non-zero exit as error
- **Fix**: Check `$LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq 3010`

## First-Launch Dialog Sequence
bcWebCam shows these dialogs on first launch (coordinates in 1280x720):
1. **"bcWebCam - First Start"** welcome dialog — OK button at (~639, 536)
2. **"How to read barcodes in 3 steps"** tutorial — shown as main window content (NOT a dialog)
3. **"bcWebCam - Critical Error"** no-webcam error — OK button at (~783, 418)

After warm-up launch + graceful close (Alt+F4), the First Start dialog is suppressed on subsequent launches. The no-webcam error always appears.

## Options Dialog (gear icon at ~569, 658)
Default settings verified via visual grounding:
- **Start WebCam automatically**: unchecked
- **Display inactive window half-transparent**: checked
- **Delete recognized Barcode after [0] Seconds**: unchecked, value 0
- **Send barcode data to active application**: checked
- **Append terminating character**: `<ENTER>` selected (NOT "No")
- **Copy read barcode to clipboard**: unchecked
- **Acoustic signal**: checked
- **Open detected URL**: unchecked
- **Application always on top**: unchecked
- **Check for update on start**: checked
- **Current Device**: `<no device available>`
- **OK button**: (~609, 590), **Cancel**: (~688, 590)

## Barcode Options Dialog (barcode icon at ~539, 658)
Default settings:
- **Read EAN barcodes**: checked
- **Read QR Codes**: checked
- **Read Data Matrix**: unchecked
- **Read Aztec Codes**: unchecked
- **Read Linear Barcodes**: unchecked
- **Read PDF 417**: unchecked
- **OK button**: (~551, 609), **Cancel**: (~628, 609)

## Tasks (5 total, all easy/configuration)
1. **set_terminating_character**: Select `<TAB>` radio button (default: `<ENTER>`)
2. **enable_clipboard_copy**: Check "Copy read barcode to clipboard" (default: unchecked)
3. **enable_url_detection**: Check "Open detected URL" (default: unchecked)
4. **configure_barcode_timeout**: Check + set "Delete recognized Barcode after [500] Seconds" (default: unchecked/0)
5. **enable_linear_barcodes**: Check "Read Linear Barcodes" in Barcode Options (default: unchecked)

## File Structure
```
benchmarks/cua_world/environments/bcwebcam_env/
  env.json                              # Environment config
  scripts/
    install_bcwebcam.ps1                # pre_start: download, install, generate barcodes
    setup_bcwebcam.ps1                  # post_start: warm-up, desktop shortcut, copy data
    task_utils.ps1                      # Shared functions (Find-BcWebCamExe, Launch, Dismiss, INI utils)
  tasks/
    set_terminating_character/          # task.json, setup_task.ps1, verifier.py
    enable_clipboard_copy/
    enable_url_detection/
    configure_barcode_timeout/
    enable_linear_barcodes/
  data/
    barcodes/
      product_barcodes.csv              # 10 real EAN-13 product codes
      qr_codes.csv                      # 4 real QR code URLs + 1 vCard
  evidence_docs/
    Readme.md                           # Full documentation with log snippets
    01_task_start_state.png             # bcWebCam main window visible
    02_options_dialog.png               # Options dialog with default settings
    03_barcode_options_dialog.png       # Barcode Options dialog
```

### 5. Edge auto-restore from Windows 11 checkpoint
- **Bug**: Windows 11 auto-restores previously running applications when VM resumes from savevm checkpoint
- **Effect**: Edge browser covers bcWebCam, interfering with dialog dismissal clicks
- **Fix**: `schtasks /IT`-based Edge killer (`Start-EdgeKillerTask`) runs `taskkill /F /IM msedge.exe` every 2s in Session 1 (NOT `Start-Job` which runs in Session 0 and is unreliable)
- **Also**: `Close-Browsers` function disables Edge via registry policies (`StartupBoostEnabled=0`, `BackgroundModeEnabled=0`, `RestoreOnStartup=5`), clears all-profile session data, and `DisableAutomaticRestartSignOn=1`
- **Post_start**: Aggressive 5-iteration Edge kill loop before checkpoint save; OneDrive notification suppression (toast disabled, auto-start removed, OneDrive.exe killed)

### 6. Win32 API window management
- **Bug**: PyAutoGUI console window covers bcWebCam dialogs; coordinate clicks hit console instead
- **Fix**: Win32 P/Invoke (`SetForegroundWindow`, `ShowWindow`, `GetForegroundWindow`) via `Add-Type` in PowerShell
- **Functions**: `Minimize-PyAutoGUIConsole`, `Set-BcWebCamForeground`, `Test-BcWebCamForeground`, `Ensure-BcWebCamReady`
- **Pattern**: Minimize console → bring bcWebCam to foreground → verify via `GetForegroundWindow` → retry loop

### 7. OneDrive notification popup
- **Bug**: OneDrive "Turn On Windows Backup" notification appears over bcWebCam
- **Fix**: Disabled toast notifications (`ToastEnabled=0`), removed OneDrive from auto-start registry, killed OneDrive.exe in post_start

## Key Patterns
- **Warm-up launch**: Launch bcWebCam → dismiss dialogs → graceful close (Alt+F4) → force kill fallback
- **Per-task setup**: `Start-EdgeKillerTask` (schtasks) → `Close-Browsers` → Kill bcWebCam → Launch via `schtasks /IT` → `Close-Browsers` again → `Dismiss-BcWebCamDialogs` (Win32 foreground + Alt+Tab + Enter) → `Ensure-BcWebCamReady` (verification loop) → `Stop-EdgeKillerTask`
- **Barcode images**: Generated at install time using python-barcode and qrcode libraries from CSV data
- **INI file**: bcWebCam uses its own defaults; pre-written INI was not being read correctly, so removed
