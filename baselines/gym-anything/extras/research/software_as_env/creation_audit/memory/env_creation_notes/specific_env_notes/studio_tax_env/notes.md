> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# StudioTax 2024 Environment - Implementation Notes

Notes covering StudioTax-specific patterns discovered during setup on Windows 11 QEMU VM.

---

## 1. Installation: GUI Automation Required (Advanced Installer)

StudioTax 2024 uses **Advanced Installer** (not NSIS, not Inno Setup, not WiX). There are **no working silent install flags**. The `/S`, `/VERYSILENT`, and `/quiet` flags all fail.

**Installer download URL:**
```
https://www.downloadstudiotax.com/ver24/StudioTax2024Install.exe
```

**Size:** ~65 MB

**Installation method:** Launch via `schtasks /IT` in the interactive desktop session, then automate clicking through the wizard using a Python script that connects to the PyAutoGUI server (TCP port 5555).

### Installer Wizard Steps (coordinates at 1280x720)

| Step | Page | Action | Coordinates |
|------|------|--------|-------------|
| 1 | Language Selection | Click "Next >" | (816, 590) |
| 2 | Welcome | Click "Next >" | (816, 590) |
| 3 | License Agreement | Click "I accept" radio | (535, 517) |
| 3b | License Agreement | Click "Next >" | (815, 590) |
| 4 | Ready to Install | Click "Install" | (815, 590) |
| 5 | Setup Complete | Click "Finish" | (815, 590) |

Installation takes ~30 seconds after clicking Install. Total automation time: ~90 seconds.

**Install path:** `C:\Program Files\BHOK IT Consulting Inc\StudioTax 2024\StudioTax.exe`

## 2. Process Names

| Process | Description |
|---------|-------------|
| `StudioTax` | Main GUI application (StudioTax.exe) |
| `CheckUpdates` | Update checker (CheckUpdates.exe) |

**Important:** The exe is `StudioTax.exe`, NOT `StudioTax2024.exe`. The company name in the path is `BHOK IT Consulting Inc` (with "Inc").

Kill command:
```powershell
Get-Process StudioTax* -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process CheckUpdates -ErrorAction SilentlyContinue | Stop-Process -Force
```

## 3. Launching StudioTax

StudioTax must be launched from the interactive desktop session (Session 1), not SSH (Session 0). Use the `schtasks /IT` pattern:

```powershell
# Create batch launcher (handles path with spaces)
$bat = "C:\Windows\Temp\launch_st.bat"
Set-Content -Path $bat -Value '@echo off\nstart "" "C:\Program Files\BHOK IT Consulting Inc\StudioTax 2024\StudioTax.exe"'
schtasks /Create /TN "LaunchStudioTax" /TR "cmd /c $bat" /SC ONCE /SD 01/01/2099 /ST 00:00 /RL HIGHEST /IT /F
schtasks /Run /TN "LaunchStudioTax"
```

## 4. Start Page Layout (1280x720)

StudioTax opens to a Start Page with:
- "Open an existing return..." button (large, center-left)
- "Create a new return..." button (large, center-left)
- "Create a new 2024 return from the 2023 return..." (large, center-left)
- "Recent Returns" list below (initially empty)
- Help links panel on the right
- Top-right: Activate, Updates, Francais, Exit buttons

No first-run dialogs were observed during testing — the app launches directly to the Start Page.

## 5. Data Source

All tax scenario data comes from the **Canada Revenue Agency (CRA) "Learn About Your Taxes" educational program** (official CRA scenarios). These are real-world representative data based on actual tax forms (T4, T5, T4A, T5007, T2202, Schedule 9, etc.).

Five scenario files, each with a distinct taxpayer profile:
- **Jonah Smith** (NL, bakery, $18K T4) — easy
- **Terry Lee** (BC, pizza, $12K + tips + RRSP) — medium
- **Farah Awan** (ON, student, T4+T5007+T4A+T2202) — hard
- **Maria Chen** (ON, investments, T5 dividends + T5008 capital gains) — hard
- **Han Park** (ON, 2 employers, medical + donations + dependants) — hard

## 6. File Format

StudioTax saves returns as `.24t` files (proprietary format for tax year 2024). These are text-based and can be searched for string content (taxpayer names, amounts, SINs) for verification.

## 7. SSH/PyAutoGUI Notes

- SSH user: `Docker`, password: `GymAnything123!`
- PyAutoGUI server: port 5555 (on the VM, forwarded to a host port)
- Screen resolution: 1280x720
- SSH runs in Session 0 — **cannot** interact with GUI directly
- All GUI interaction must go through PyAutoGUI TCP server or schtasks /IT
- The `cmd /c` prefix is needed for Windows commands over SSH (bare `dir` etc. fail)

## 8. Common Pitfalls

1. **Silent install doesn't work** — Must use GUI automation
2. **Exe name is StudioTax.exe** not StudioTax2024.exe
3. **Company path includes "Inc"** — "BHOK IT Consulting Inc" not "BHOK IT Consulting"
4. **OneDrive popup** blocks the desktop — dismiss it early in post_start
5. **PyAutoGUI API** uses named parameters (`x`, `y`, `keys`), NOT positional `args`
6. **env.reset() takes ~18 minutes** from cold start (Windows 11 boot + install + setup)
