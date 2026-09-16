> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Microsoft Word 2010 Environment — Learnings & Notes

## Installation

### Office 2010 Starter (Click-to-Run) — DOES NOT WORK on Windows 11

**Attempted approach**: Download `setupconsumerc2rolw.exe` (1.6MB bootstrapper) from Internet
Archive. This is the free, ad-supported Office 2010 Starter Edition.

**Result**: Error dialog — "Microsoft Application Virtualization is installed in an incompatible configuration"

**Root cause**: Office 2010 Starter uses Click-to-Run (C2R) which relies on App-V 4.x virtualization.
Windows 11 has built-in App-V 5.x (system DLLs in system32). The two versions are incompatible.

**Attempted fixes**:
1. Removed App-V registry keys (`HKLM:\SOFTWARE\Microsoft\AppV` and WOW6432Node) → Same error (DLLs still present)
2. Searched for KB2598285 compatibility patch → Microsoft download link returns 404 (file removed)
3. Set Windows 7 compatibility mode → No effect on the App-V conflict

**Conclusion**: Office 2010 Starter cannot be installed on Windows 11. Use the MSI-based approach.

### Office 2010 Professional Plus (MSI) — WORKS

**Source**: Internet Archive — `archive.org/details/office2010nokeyneeded_201908`
- File: "Office 2010 - No Key Needed.iso" (731MB)
- Volume label: "OFFICE 2010 - NO KEY NEEDED"

**Installation method**:
1. Mount ISO with `Mount-DiskImage`
2. Run `setup.exe /config office_config.xml` for silent Word-only install
3. Config uses `<Display Level="none" AcceptEula="yes" />` and `OptionState State="absent"` for non-Word apps
4. Unmount and cleanup

**Install path**: `C:\Program Files (x86)\Microsoft Office\Office14\WINWORD.EXE` (32-bit on 64-bit Windows)

**No activation prompts**: On first launch, Word shows no product key dialog, no sign-in, no activation nag.
The ISO title "No Key Needed" appears to have the installation pre-configured to skip activation.

### Office 365 via ODT — DOES NOT WORK

The existing `microsoft_excel_env` uses Office 365 via ODT, but it shows an undismissable
"Sign in to get started with Excel" dialog. No workaround exists without a Microsoft account.

## Service Timing

- **ISO download**: ~2-5 minutes from Internet Archive (731MB)
- **MSI installation**: ~1-2 minutes (Word-only)
- **Word launch**: ~10-12 seconds via schtasks
- **OneDrive uninstall**: ≤30 seconds
- **Total post_start**: ~90-100 seconds (including warm-up launch)
- **Task setup**: ~30 seconds

## Registry Keys (Office 14.0)

```
HKCU:\Software\Microsoft\Office\14.0\Common\General\ShownFirstRunOptin = 1
HKCU:\Software\Microsoft\Office\14.0\FirstRun\BootedRTM = 1
HKCU:\Software\Microsoft\Office\14.0\FirstRun\DisableMovie = 1
HKCU:\Software\Microsoft\Office\14.0\Word\Options\DisableBootToOfficeStart = 1
HKCU:\Software\Microsoft\Office\14.0\Registration\AcceptAllEulas = 1
HKLM:\SOFTWARE\Policies\Microsoft\Office\14.0\Common\General\ShownFirstRunOptin = 1
```

## Dialog Handling

### Document Recovery Panel
- Appears after Word is force-killed (common during warm-up cycle)
- Left-side panel with "Document Recovery" header and "Close" button
- Close button coordinates: approximately (216, 628) at 1280x720
- Handled by `Dismiss-WordDialogsBestEffort` in task_utils.ps1

### First-Run Dialogs
- With the registry keys above, no first-run dialogs were observed
- The warm-up launch in post_start ensures any residual first-run state is consumed

## Data Files

All documents created with python-docx library using real public domain content:

| File | Content Source | Task |
|------|---------------|------|
| `census_press_release.docx` | US Census Bureau press release CB24-SFS.17 (public domain) | format_headings |
| `meeting_notes_raw.docx` | Meeting notes with quarterly revenue figures | format_table |
| `company_memo_draft.docx` | Blank document | create_business_letter |

## PyAutoGUI Coordinates (1280x720)

| Element | Coordinates |
|---------|-------------|
| Document area center | (640, 400) |
| Heading 1 in Styles panel | (~833, 85) |
| Heading 2 in Styles panel | (~900, 85) |
| Normal in Styles panel | (~690, 85) |
| Document Recovery Close button | (~216, 628) |
| Safe click area (no buttons) | (400, 350) |

## SSH/PowerShell Gotchas

1. **Dollar signs ($) stripped**: When running PowerShell via SSH, `$` in variable names gets
   interpreted by the shell. Solution: write PowerShell scripts to disk and run with `-File`.

2. **Paths with (x86)**: `C:\Program Files (x86)` causes parsing issues in schtasks commands.
   Solution: use batch file wrapper (`.cmd` file) that quotes the path.

3. **schtasks /ST warning**: `WARNING: Task may not run because /ST is earlier than current time`
   is harmless — `/Run` executes immediately regardless.

4. **PowerShell strict mode + schtasks**: schtasks writes to stderr, which triggers errors under
   `$ErrorActionPreference = "Stop"`. Wrap with `$ErrorActionPreference = "Continue"` and `2>$null`.

## File Structure

```
benchmarks/cua_world/environments/microsoft_word_starter_env/
├── env.json                              # Environment config
├── scripts/
│   ├── install_word_starter.ps1          # pre_start: Download ISO + silent install
│   ├── setup_word_starter.ps1            # post_start: Registry + OneDrive + warm-up
│   ├── task_utils.ps1                    # Shared helpers (Find-WordExe, etc.)
│   └── dismiss_dialogs.ps1              # Standalone dialog dismissal
├── data/
│   ├── office_config.xml                 # Word-only silent install config
│   ├── census_press_release.docx         # US Census press release (public domain)
│   ├── meeting_notes_raw.docx            # Meeting notes with quarterly data
│   ├── company_memo_draft.docx           # Blank document
│   └── create_docx_files.py             # Script that generated the .docx files
├── tasks/
│   ├── format_headings/                  # Easy: Apply heading styles
│   ├── create_business_letter/           # Medium: Write business letter
│   └── format_table/                     # Medium: Create formatted table
└── evidence_docs/                        # Screenshots + README
```
