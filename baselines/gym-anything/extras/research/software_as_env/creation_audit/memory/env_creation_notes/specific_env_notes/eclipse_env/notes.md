> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Eclipse IDE Environment Notes

## Overview
Eclipse IDE environment for Java development tasks including Maven project management, code editing, debugging, and refactoring.

## Installation

### Base Image
- `ubuntu-gnome-systemd_highres` (1920x1080 resolution)

### Software Installed
- Eclipse IDE for Java Developers 2024-12
- OpenJDK 17
- Apache Maven 3.6.3
- GUI automation tools (scrot, wmctrl, xdotool, python3-pyautogui)

### Installation Method
Eclipse is downloaded directly from eclipse.org as a tarball and extracted to `/opt/eclipse`.

```bash
# Download Eclipse
wget -O /tmp/eclipse.tar.gz "https://www.eclipse.org/downloads/download.php?file=/technology/epp/downloads/release/2024-12/R/eclipse-java-2024-12-R-linux-gtk-x86_64.tar.gz&r=1"

# Extract to /opt
tar -xzf /tmp/eclipse.tar.gz -C /opt/
```

## Configuration

### Workspace Location
Default workspace: `/home/ga/eclipse-workspace`

### Eclipse Preferences
Auto-configured settings in `~/.eclipse/`:
- Auto-build disabled (to avoid background compilation during tasks)
- Welcome screen disabled
- Default perspective set to Java

### Firefox Browser
Firefox is installed alongside Eclipse for web-related tasks, with first-run wizards disabled.

## Task Setup Patterns

### Project Files
Eclipse projects require metadata files to be recognized:
- `.project` - Eclipse project descriptor
- `.classpath` - Java build path configuration
- `.settings/` - Project-specific settings

Example `.project` file:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<projectDescription>
    <name>project-name</name>
    <natures>
        <nature>org.eclipse.jdt.core.javanature</nature>
        <nature>org.eclipse.m2e.core.maven2Nature</nature>
    </natures>
</projectDescription>
```

### Pre-task Setup
1. Copy project files to workspace
2. Create Eclipse metadata files
3. Wait for Eclipse to detect project
4. Dismiss any dialogs
5. Take initial screenshot

## GUI Interaction Tips

### Keyboard Shortcuts (Preferred)
- `Ctrl+Shift+R` - Open Resource (quick file search)
- `Ctrl+F` - Find/Replace
- `Alt+F` - File menu
- `Alt+P` - Project menu
- `F5` - Refresh
- `Ctrl+S` - Save
- `Alt+F5` - Maven Update Project

### Menu Navigation
Direct menu clicks sometimes fail due to SWT/X11 interactions. Use keyboard shortcuts when possible.

### Window Management
```bash
# Focus Eclipse window
DISPLAY=:1 wmctrl -a Eclipse

# Maximize Eclipse
DISPLAY=:1 wmctrl -r Eclipse -b add,maximized_vert,maximized_horz

# Check what windows are open
DISPLAY=:1 wmctrl -l
```

## Verification Patterns

### Maven Projects
1. Check pom.xml exists and has expected content
2. Parse pom.xml using XML ElementTree
3. Verify dependencies are present
4. Check for compiled .class files in target/classes
5. Verify class files have valid Java magic bytes (CAFEBABE)

### XML Namespace Handling
Maven pom.xml uses namespaces. Use full namespace URI for element lookup:
```python
maven_ns = '{http://maven.apache.org/POM/4.0.0}'
aid = dep.find(f'{maven_ns}artifactId')
```

## Known Issues

### Eclipse Problems View Stale
Eclipse's Problems view may not update after external changes. Solutions:
- Project > Clean
- Maven > Update Project
- Close and reopen files

### Firefox Auto-launch
Firefox sometimes launches automatically. Close it with:
```bash
DISPLAY=:1 wmctrl -c Firefox
```

### Dialog Focus Issues
Import/preference dialogs may appear but not be visible. Check with wmctrl:
```bash
DISPLAY=:1 wmctrl -l | grep -i import
```

## Resource Requirements
- CPU: 4 cores
- Memory: 8GB (Eclipse + Maven + desktop)
- Network: Required for Maven dependency downloads
- GPU: Not required
