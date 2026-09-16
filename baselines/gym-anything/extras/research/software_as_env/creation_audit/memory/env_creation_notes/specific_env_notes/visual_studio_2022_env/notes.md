> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Visual Studio 2022 Community Environment - Creation Notes & Lessons Learned

## Overview

Created `visual_studio_2022_env` for C#/.NET IDE tasks. Uses VS Community 2022 with ManagedDesktop workload on Windows 11 QEMU VM. 62-day Enterprise Evaluation grace period means no sign-in required for ephemeral VMs.

## Key Decisions

### Why Community 2022 (not VS Code)?
- VS Code already has a Linux-based env in the codebase
- Full VS 2022 provides richer IDE tasks: NuGet management, solution/project creation, GUI build tools
- Tests agent's ability to navigate complex IDE interfaces

### Why ManagedDesktop Workload?
- Includes C# compiler, .NET SDK, IntelliSense, NuGet, console app templates
- ~6-8 GB download but covers all C#/.NET desktop development needs
- Smaller than installing multiple individual workloads

### Real Data: InventoryManager Console App
- Created via `dotnet new console` during post_start
- Overwritten Program.cs with real inventory management logic (5 products, formatted table output)
- Broken version has 2 injected errors: `InventoryItm` typo (CS0246) + missing semicolon (CS1002)
- Build verified to succeed on clean version, fail on broken version

## Installation Quirks

### Non-ASCII Characters in PS1 Files - CRITICAL
- PowerShell on Windows **CANNOT parse** em dashes (--), box-drawing chars, or other non-ASCII in .ps1 files transferred via SCP
- Error: `Unexpected token 'download' in expression or statement` (the -- before "download" was mangled)
- **Fix**: Use ASCII-only characters in all PowerShell scripts. Use `--` instead of `--`.
- Exception: Here-strings (@'...'@) that contain C# source code are fine because PowerShell treats them as opaque literal strings

### Bootstrapper vs Full Installer
- VS uses a tiny bootstrapper (~4.4 MB) that downloads the actual installer + workload
- `--wait` flag blocks until install completes (15-30 min)
- `--passive` shows progress UI but requires no user interaction
- Exit code 0 = success (unlike Office 2010 which returns 3010)

### First-Run Dialog Sequence
1. **"Sign in to Visual Studio"** - Must click "Skip and add accounts later" link at (930, 442)
2. **"Personalize your Visual Studio experience"** (theme picker) - Must click "Start Visual Studio" at (930, 487)
3. **"Are you sure you want to exit?"** - Appears if Escape was pressed during sign-in dialog. Click "No" at (755, 418)

After completing first-run once, subsequent launches skip all dialogs.

### GitHub Copilot Chat Panel
- VS 2022 Community includes Copilot Chat by default
- Shows in right panel on first solution open
- Does not block functionality
- Solution Explorer tab available at bottom of same panel area

### Solution Files
- `dotnet new console` does NOT create .sln files
- Must create separately: `dotnet new sln` + `dotnet sln add project.csproj`
- VS can open .csproj directly, but .sln provides the full "solution" experience

## Setup Script Notes

### Registry Keys (VS 2022 / VSCommon 17.0)
- `HKLM:\SOFTWARE\Microsoft\VSCommon\17.0\SQM` OptIn=0 (disable telemetry)
- `HKLM:\SOFTWARE\Microsoft\VisualStudio\Setup` BackgroundDownloadDisabled=1 (disable updates)
- `DOTNET_CLI_TELEMETRY_OPTOUT=1` environment variable (Machine scope)
- `DOTNET_NOLOGO=1` environment variable

### VS Private Registry
- VS 2022 uses a private registry hive, not standard HKCU
- `vsregedit.exe` can modify VS-specific settings
- For this env, standard HKLM registry + environment variables are sufficient

### NuGet Cache Warming
- Build InventoryManager once during post_start to download NuGet packages
- Then clean build output (rm bin/obj) so the task starts fresh
- This prevents long NuGet restore delays during task execution

## Task-Specific Notes

### create_console_project
- VS must be launched WITHOUT a .sln to show the Start Window
- Agent clicks "Create a new project" -> selects "Console App" -> names it "HelloWorld"
- Verify: `C:\Users\Docker\source\repos\HelloWorld\HelloWorld.csproj` exists

### build_existing_solution
- Ctrl+Shift+B triggers Build > Build Solution
- Output window shows build results including success/failure count
- Status bar shows "Build succeeded" on success
- Build takes ~6 seconds on first build (NuGet already cached)

### fix_build_error
- Two injected errors in Program.cs:
  1. `InventoryItm` (typo) on line with `var inventory = new List<InventoryItm>` - CS0246
  2. Missing semicolon on `decimal grandTotal = inventory.Sum(i => i.TotalValue)` - CS1002
- Error List panel shows errors after build attempt
- Agent must fix both errors and rebuild successfully

### add_nuget_package
- Right-click project in Solution Explorer > Manage NuGet Packages
- Browse tab > search "Newtonsoft.Json" > Install
- License acceptance dialog appears
- Verify: `<PackageReference Include="Newtonsoft.Json"` in .csproj

### create_class_file
- Right-click project > Add > Class > name "InventoryReport.cs"
- Agent must add a `GenerateSummary` method
- Verify: InventoryReport.cs exists with public class

## File Structure

```
benchmarks/cua_world/environments/visual_studio_2022_env/
|-- env.json                              # Environment config
|-- scripts/
|   |-- install_vs2022.ps1               # pre_start: Download bootstrapper, silent install
|   |-- setup_vs2022.ps1                 # post_start: Registry, projects, warm-up
|   +-- task_utils.ps1                   # Find-VS2022Exe, Launch-VS2022Interactive, etc.
|-- data/                                 # (empty - projects created via dotnet CLI)
|-- tasks/
|   |-- create_console_project/           # Easy: create new C# Console App
|   |-- build_existing_solution/          # Easy: build InventoryManager (Ctrl+Shift+B)
|   |-- fix_build_error/                  # Medium: fix 2 compile errors
|   |-- add_nuget_package/               # Medium: add Newtonsoft.Json via NuGet
|   +-- create_class_file/               # Medium: add InventoryReport.cs class
+-- evidence_docs/
    |-- README.md                         # Full evidence with logs
    |-- create_console_project_start_state.png
    |-- build_existing_solution_start_state.png
    |-- build_existing_solution_completed.png
    |-- fix_build_error_start_state.png
    |-- add_nuget_package_start_state.png
    +-- create_class_file_start_state.png
```

## Comparison with VSCode Linux Env

| Feature | VSCode (Linux) | VS 2022 (Windows) |
|---------|---------------|-------------------|
| Platform | Ubuntu QEMU | Windows 11 QEMU |
| IDE | VS Code (Electron) | Visual Studio 2022 |
| Language focus | Multiple (JS/Python) | C#/.NET |
| Project system | Folder-based | Solution/Project (.sln/.csproj) |
| Build system | Tasks/terminal | MSBuild integrated |
| Package manager | npm/pip | NuGet |
| Install size | ~200 MB | ~6-8 GB |
| Sign-in required | No | No (62-day grace) |
