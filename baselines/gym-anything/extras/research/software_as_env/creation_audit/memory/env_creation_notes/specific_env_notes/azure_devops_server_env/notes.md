> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Azure DevOps Server Environment Notes

## Stack
- **Application**: Azure DevOps Server 2022 Express Edition (free, 5-user limit)
- **Base**: Windows 11 QEMU VM (`windows-11`), 10GB RAM, 4 CPU
- **Database**: SQL Server 2022 Express (installed automatically during config)
- **Web Server**: IIS (configured by tfsconfig)
- **URL**: `http://localhost/DefaultCollection` (port 80, no `/tfs` prefix for Express)
- **Auth**: Windows NTLM (automatic for Docker user, no PAT needed)
- **Process Template**: Agile (`adcc42ab-9882-485e-a3ed-7678f01f66bc`)

## Installation (pre_start)

### Download
- Web installer URL: `https://go.microsoft.com/fwlink/?LinkId=2269947` (~3.3MB)
- The web installer downloads the full payload during `/Silent` install
- Total install time: ~25 minutes (download + install + configuration)

### Silent Install
```powershell
Start-Process $installer -ArgumentList "/Silent" -Wait
```
- Exit code 0 = success
- Installs binaries to `C:\Program Files\Azure DevOps Server 2022\`

### Unattended Configuration (CRITICAL)
```powershell
# Generate config INI
& "$tfsConfig" unattend /create /type:NewServerBasic
# Modify INI for SQL Express and initial collection
# Run configuration
& "$tfsConfig" unattend /configure /unattendfile:$iniPath /continue
```
- `tfsconfig.exe` location: `C:\Program Files\Azure DevOps Server 2022\Tools\tfsconfig.exe`
- Config goes through 8 steps: IIS, SQL Express install, databases, services, collection, website
- **CRITICAL**: Must set `InstallSqlExpress=True` in INI (Express auto-installs SQL)
- **CRITICAL**: Must set `CreateInitialCollection=True` and `CollectionName=DefaultCollection`
- Config takes 10-20 minutes; use `/continue` flag for non-interactive

### Services
- `TFSJobAgent`: Background job agent (must be Running)
- SQL Server: `MSSQL$SQLEXPRESS` (check with `Get-Service *SQL*`)
- IIS: `W3SVC` (web server)

## REST API

### Base Pattern
```powershell
Invoke-RestMethod -Uri "$baseUrl/_apis/...?api-version=7.1" -UseDefaultCredentials -ContentType "application/json"
```
- Always use `-UseDefaultCredentials` for NTLM auth
- API version: `7.1` works with Azure DevOps Server 2022

### Work Item Creation (CRITICAL GOTCHAS)

1. **State must be default ("New")**: Cannot set `System.State` to "Active" or other values during creation. Work items always create in their default initial state.

2. **AcceptanceCriteria is User Story only**: The field `Microsoft.VSTS.Common.AcceptanceCriteria` only exists on User Story type in the Agile template. Bugs have `Microsoft.VSTS.TCM.ReproSteps` instead.

3. **StrictMode property access**: With `Set-StrictMode -Version Latest`, accessing non-existent properties on `ConvertFrom-Json` objects throws. Use `$obj.PSObject.Properties.Name -contains 'propName'` before accessing.

4. **Content-Type for work items**: Must use `application/json-patch+json` (not `application/json`).

5. **Work item type in URL**: Escape as `$User%20Story`, `$Bug`, `$Task`.

### Git Push API (CRITICAL)

1. **25MB request size limit**: Azure DevOps Server has a max request size. Use explicit file lists instead of `Get-ChildItem -Recurse`.

2. **Use `-Compress` on ConvertTo-Json**: Reduces JSON payload size significantly.

3. **UTF-8 encoding**: Pass body as `[System.Text.Encoding]::UTF8.GetBytes($json)` to avoid encoding issues.

4. **Single-element array unwrap**: PowerShell 5.1's `ConvertTo-Json` unwraps single-element arrays to plain objects. For ref creation (which expects an array), manually wrap: `"[$itemJson]"`.

### Iteration/Sprint Setup

1. Create classification nodes: `POST /_apis/wit/classificationnodes/iterations`
2. Add to team iterations: `POST /_apis/work/teamsettings/iterations` with `{ "id": "<node-identifier>" }`
3. Default iterations (Iteration 1-3) are created automatically by the Agile template. **Remove them** from team iterations after adding Sprint 1-4: `DELETE /_apis/work/teamsettings/iterations/{id}`

## Edge Browser Configuration

### Required Registry Policies (`HKLM:\SOFTWARE\Policies\Microsoft\Edge`)
- `HideFirstRunExperience` = 1 (suppress first-run wizard)
- `AutoImportAtFirstRun` = 4 (don't auto-import)
- `StartupBoostEnabled` = 0 (prevent background startup)
- `HideRestoreDialogEnabled` = 1 (suppress crash recovery dialog)
- `RestoreOnStartup` = 4 (don't restore previous pages)
- `AuthServerAllowlist` = "localhost" (enable automatic NTLM auth)
- `AuthNegotiateDelegateAllowlist` = "localhost" (enable NTLM delegation)

### schtasks /IT Pattern for Edge
```powershell
$futureTime = (Get-Date).AddMinutes(2).ToString("HH:mm")
schtasks /Create /TN "TaskName" /TR "cmd /c script.cmd" /SC ONCE /ST $futureTime /RL HIGHEST /IT /F
schtasks /Run /TN "TaskName"
```
- **CRITICAL**: Use dynamic future time, NOT `/ST 00:00` (always in past, causes warning)
- Must use `/IT` for interactive desktop session (Session 0 isolation in Windows)

## SPA Routing Gotchas

### Sprint Board URL Redirect
- Direct Sprint board URL (`_sprints/board/{team}/{project}/{sprint}`) returns HTTP 200 from server but SPA client-side JavaScript redirects to `_sprints/directory`
- **Workaround**: Use Backlogs URL (`_backlogs/backlog/{team}/Stories`) instead

### Kanban Board Doesn't Show API-Created Items (CRITICAL)
- Work items created via the REST API do NOT appear on the Kanban board (`_boards/board/...`) until the board has been manually initialized through the browser UI
- The `System.BoardColumn` field is not set on API-created items and cannot be set via API (returns 400)
- Items created from the board UI (via "+ New item" button) DO appear immediately
- **Workaround**: Use Backlogs view (`_backlogs/backlog/.../Stories`) instead of Board view for task start states — Backlogs reliably show all items

## Windows 11 Environment Notes

### OneDrive / Toast Notification Suppression (CRITICAL)
- OneDrive auto-starts and shows "Turn On Windows Backup" notification toast
- The toast persists even after OneDrive is killed/uninstalled because it's a Windows system toast
- **Full suppression requires ALL of**:
  1. Kill OneDrive: `Get-Process OneDrive* | Stop-Process -Force`
  2. Uninstall: `OneDriveSetup.exe /uninstall`
  3. Disable OneDrive policy: `HKLM:\...\OneDrive\DisableFileSyncNGSC=1`
  4. Disable toast notifications: `HKCU:\...\PushNotifications\ToastEnabled=0`
  5. Disable backup reminder: `HKCU:\...\Notifications\Settings\Windows.SystemToast.BackupReminder\Enabled=0`
  6. Disable cloud content: `HKLM:\...\CloudContent\DisableWindowsConsumerFeatures=1`
  7. Disable notification center: `HKCU:\...\Policies\...\Explorer\DisableNotificationCenter=1`
  8. Restart explorer to clear existing toasts: `Stop-Process -Name explorer; Start-Process explorer`
  9. Use PyAutoGUI to click dismiss on any remaining toasts

### PyAutoGUI Interaction for Toast Dismissal
- The PyAutoGUI server runs on port 5555 inside the VM
- Can connect via TCP socket with JSON commands: `{"action":"click","x":X,"y":Y,"button":"left","clicks":1}`
- `Clean-DesktopForTask` function in task_utils.ps1 uses this to dismiss any lingering notifications

### SSH
- User: `Docker` / Password: `GymAnything123!`
- PowerShell is the default shell (not cmd)
- PowerShell does NOT support `&&` operator; use `;` instead
- Use `-ExecutionPolicy Bypass` for script execution

## Data

### Work Items (work_items.json)
- 15 realistic work items for a "Tailwind Traders Inventory API" project
- 7 User Stories, 4 Bugs, 4 Tasks
- Distributed across Sprint 1-4
- All created in "New" state (cannot set Active on creation)
- IDs start at 1 on fresh install

### Git Repository
- Flask-based inventory management API
- 9 files: app.py, models.py, routes.py, config.py, requirements.txt, Dockerfile, README.md, .gitignore, tests/test_app.py
- Feature branch: `feature/add-search-endpoint` with search.py

## Tasks (4 total)

| Task | Start URL | Start State |
|------|-----------|-------------|
| create_user_story | `_backlogs/backlog/.../Stories` | Backlog with 7 User Stories, "+ New Work Item" button |
| create_bug_report | `_workitems` | Work Items list with recently updated items |
| resolve_bug_work_item | `_backlogs/backlog/.../Stories` | Backlog with 7 User Stories |
| create_pull_request | `_git/TailwindTraders` | Repos page with files, "Create a pull request" banner |

## Known Issues
- Kanban board doesn't show API-created items (use Backlogs view instead)
- Azure DevOps tutorial popups appear on first visit to Backlogs page ("Got It" and "Planning" tooltips); agent needs to dismiss them or use PyAutoGUI
- Edge crash recovery dialog if Edge was previously killed (suppressed via HideRestoreDialogEnabled policy)
- Post-start script idempotency: Work item seeding checks for existing items and skips if any found; Git init checks for existing refs and skips if already initialized
