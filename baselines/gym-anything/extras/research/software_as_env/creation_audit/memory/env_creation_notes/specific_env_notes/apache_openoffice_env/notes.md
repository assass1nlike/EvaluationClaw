> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Apache OpenOffice Environment Notes

## Overview
Apache OpenOffice Writer environment for document processing tasks.

## Installation Details

### Download Source
- Apache OpenOffice 4.1.16 from SourceForge
- URL: `https://sourceforge.net/projects/openofficeorg.mirror/files/4.1.16/binaries/en-US/`
- File: `Apache_OpenOffice_4.1.16_Linux_x86-64_install-deb_en-US.tar.gz`

### Installation Location
- Binary: `/opt/openoffice4/program/soffice`
- Config directory: `~/.openoffice/4/user/`

### Dependencies
- Java Runtime (default-jre)
- LibreOffice MUST be removed (conflicts)
- X11 libraries (libxinerama1, libxtst6, etc.)
- Automation tools: xdotool, wmctrl, scrot

## Key Learnings

### First-Run Wizard
Apache OpenOffice 4.x has a mandatory first-run wizard that:
1. Shows an "Online Update" configuration dialog
2. Shows a "Welcome to OpenOffice" wizard with multiple steps
3. The `--nofirststartwizard` flag does NOT skip this wizard reliably

**Solution**: Complete the wizard programmatically by:
1. Detecting wizard window with `xdotool search --name "Welcome"`
2. Navigating through pages with keyboard (Tab + Return)
3. After wizard, the Start Center appears - use Ctrl+N to create new document

### Start Center
After completing the wizard, OpenOffice shows a Start Center instead of Writer directly.
- Use `Ctrl+N` keyboard shortcut to create a new blank document
- Or double-click on "Text Document" icon

### Configuration File
The `registrymodifications.xcu` file uses XML format:
```xml
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
  <item oor:path="/org.openoffice.Office.Common/Misc">
    <prop oor:name="FirstRun" oor:op="fuse">
      <value>false</value>
    </prop>
  </item>
</oor:items>
```

Note: Setting `FirstRun=false` does NOT skip the wizard - it only prevents the wizard from running again after first completion.

### Window Detection
- OpenOffice windows may not appear immediately in `wmctrl -l`
- Use `xdotool search --name "OpenOffice"` for detection
- Writer window title: "Untitled 1 - OpenOffice Writer"

## Task Setup Pattern

1. Launch soffice with `--writer --norestore` flags
2. Wait for process with `wait_for_process "soffice"`
3. Handle Start Center by sending `Ctrl+N`
4. Handle first-run wizard with Tab navigation
5. Wait for Writer window to appear
6. Focus window and dismiss any extra dialogs

## Verification Approach

Uses ODT file parsing with `odfpy` library:
- Extract text content from ODT
- Check for required elements (company name, recipient, date, etc.)
- Verify file was saved to correct location

## Differences from LibreOffice

| Aspect | LibreOffice | Apache OpenOffice |
|--------|-------------|-------------------|
| Config path | `~/.config/libreoffice/4/user/` | `~/.openoffice/4/user/` |
| Binary location | `/usr/bin/soffice` | `/opt/openoffice4/program/soffice` |
| First-run wizard | Can be skipped with config | Must be completed |
| Installation | apt-get | SourceForge download + dpkg |

## Testing Commands

```bash
# Check installation
ls -la /opt/openoffice4/program/soffice

# Check Java
java -version

# Launch Writer
export DISPLAY=:1 && /opt/openoffice4/program/soffice --writer

# Take screenshot
scrot /tmp/screenshot.png
```
