> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# ProjectLibre Environment Notes

## Overview
ProjectLibre is an open-source Java-based project management desktop application — a free alternative to Microsoft Project. It supports Gantt charts, task scheduling, resource management, and project dependencies.

**Version**: 1.9.3
**License**: CPAL-1.0
**Package**: `.deb` from SourceForge

## Critical: File Format

### DO NOT use .pod files from Python
ProjectLibre's native `.pod` format is **Java serialized objects** (Java object serialization stream). It is NOT a ZIP file, despite what you might assume. Attempting to create a `.pod` file with Python (even a valid ZIP containing XML) will cause:
```
java.io.StreamCorruptedException: invalid stream header: 504B0304
```

### USE MSPDI XML format instead
ProjectLibre natively supports **MSPDI XML** (Microsoft Project XML schema) via file extension detection. Any file with `.xml` extension is automatically imported as MSPDI XML.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <Name>My Project</Name>
  ...
</Project>
```

Key elements:
- `Task/UID` and `Task/ID` (both required)
- `Task/Duration` format: `PT{hours}H0M0S` (e.g., `PT80H0M0S` = 80 hours = 10 days)
- `Task/Milestone`: `1` for milestone, `0` for regular task
- `Task/Summary`: `1` for summary/parent task, `0` for regular
- `Task/PredecessorLink/Type`: `1` = Finish-to-Start (most common)
- `Resource/Type`: `0` = Work resource (person)
- `Resource/StandardRate`: hourly rate in base currency
- `Assignment/TaskUID` + `Assignment/ResourceUID` + `Assignment/Work` (duration format)

## Installation

### .deb package approach (recommended)
```bash
wget "https://downloads.sourceforge.net/project/projectlibre/ProjectLibre/1.9.3/projectlibre_1.9.3-1.deb"
apt-get install -f ./projectlibre_1.9.3-1.deb
```

Requires Java (JRE):
```bash
apt-get install -y default-jre
```

Also install UI automation tools:
```bash
apt-get install -y xdotool wmctrl
```

### Warm-up launch
ProjectLibre shows first-run dialogs (welcome screen, recent projects). Use Pattern #14 (warm-up launch in post_start):
```bash
su - ga -c "DISPLAY=:1 setsid projectlibre > /tmp/projectlibre_warmup.log 2>&1 &"
# Wait for window, dismiss with Escape/Return, then kill
```

## Launching with a Project File

```bash
su - ga -c "DISPLAY=:1 setsid projectlibre '/path/to/project.xml' > /tmp/projectlibre_task.log 2>&1 &"
```

Window detection (from hooks where su is needed):
```bash
DISPLAY=:1 wmctrl -l 2>/dev/null | grep -qi "projectlibre\|Commercial Construction\|project.xml"
```

Wait loop (40 iterations, 1s each; large 146-task project needs 8s extra after window appears):
```bash
for i in $(seq 1 40); do
    if DISPLAY=:1 wmctrl -l 2>/dev/null | grep -qi "projectlibre\|Commercial Construction\|project.xml"; then
        echo "Window appeared after ${i}s"
        break
    fi
    sleep 1
done
sleep 8  # Allow full UI load for 146-task project
```

## Modifying Project XML for Task Setup

When tasks need a specific starting state, modify the XML before launching:

```python
import xml.etree.ElementTree as ET

task_file = "/home/ga/Projects/current_task.xml"
ns = "http://schemas.microsoft.com/project"
ET.register_namespace('', ns)  # Prevents ns0: prefix mangling

tree = ET.parse(task_file)
root = tree.getroot()

# Find and remove specific assignment
assignments = root.find(f'{{{ns}}}Assignments')
for assignment in assignments.findall(f'{{{ns}}}Assignment'):
    task_uid = assignment.findtext(f'{{{ns}}}TaskUID', '')
    resource_uid = assignment.findtext(f'{{{ns}}}ResourceUID', '')
    if task_uid == '10' and resource_uid == '5':
        assignments.remove(assignment)

# Write back - must use encoding='unicode' for correct XML declaration
tree.write(task_file, encoding='unicode', xml_declaration=True)
```

**Important**: Use `ET.register_namespace('', ns)` before writing to avoid namespace prefix mangling (which would produce `ns0:Task` instead of `Task`).

## Real Project Data Source

**CRITICAL**: This environment uses **real data only** (no synthetic/handwritten projects).

**Source**: "Commercial construction project plan.mpp" from `cyclingzealot/projectlibre-jlam` GitHub repo
**Format**: MS Project 2004 binary (.mpp), converted to MSPDI XML using MPXJ library
**File**: `assets/sample_project.xml` (555KB), copied to `/home/ga/Projects/samples/sample_project.xml`

**Project Stats**: 146 tasks, 33 resources
**Content**: Three-story commercial office building construction schedule (Jan–Dec 2000)
**Phases**: General Conditions, Long Lead Procurement, Mobilize on Site, Site Grading and Utilities, Foundations, Structural Frame, Exterior Closure, Roofing, Interior Work, Mechanical/Electrical, Finishes, Commissioning

**Key Task UIDs used in tasks**:

| UID | Task Name | Used In |
|-----|-----------|---------|
| 7   | Obtain building permits (4 days → 6 days) | `update_task_duration` |
| 22  | Set line and grade benchmarks | `assign_resource_to_task` |
| 27  | Rough grade site (cut and fill) | `add_task_dependency` (predecessor) |
| 28  | Install storm drainage | `add_task_dependency` (dependent) |
| 44  | Strip column piers and foundation forms | `create_milestone` (insert after) |
| 137 | Complete Final Inspections | `add_new_task` (insert before) |

**Key Resource UIDs**:
| UID | Resource Name | Used In |
|-----|---------------|---------|
| 7   | G.C. Survey Crew | `assign_resource_to_task` |

### Converting .mpp to MSPDI XML (MPXJ)

```python
import jpype
import jpype.imports
from pathlib import Path

jar_dir = Path("/path/to/mpxj/lib")
for jar in jar_dir.glob("*.jar"):
    jpype.addClassPath(str(jar))  # Must add ALL jars BEFORE startJVM

jpype.startJVM()
from org.mpxj.reader import UniversalProjectReader
from org.mpxj.mspdi import MSPDIWriter

reader = UniversalProjectReader()
project = reader.read("/path/to/file.mpp")
writer = MSPDIWriter()
writer.write(project, "/path/to/output.xml")
jpype.shutdownJVM()
```

**Package note**: MPXJ 15.x uses `org.mpxj` (NOT the old `net.sf.mpxj`). Install: `pip install mpxj jpype1`

## Screenshots

**IMPORTANT**: scrot does NOT work under GNOME compositor (produces black images). Use VNC screenshots:

```python
from gym_anything.runtime.runners.vnc_utils import VNCConnection
conn = VNCConnection("localhost", vnc_port, password="password")
conn.connect()
screenshot_bytes = conn.capture_screenshot()
```

## Env Configuration

- Base image: `ubuntu-gnome-systemd_highres` (1920x1080)
- Resources: 4 CPUs, 4GB RAM
- Mounts: `scripts`, `config`, `tasks`, `utils`, `assets` (all from env dir)
- User: `ga` with password `password123`, sudo nopasswd

## Tasks

| Task | Description | Verification |
|------|-------------|--------------|
| `add_task_dependency` | Add FS dependency from "Rough grade site" (task 27) to "Install storm drainage" (task 28). Setup removes UID=27 PredecessorLink from task 28 XML. | Check PredecessorLink UID=27 in saved XML or observe start date change on task 28 (1/3/00 → 2/3/00) |
| `assign_resource_to_task` | Assign G.C. Survey Crew (UID=7) to "Set line and grade benchmarks" (task 22). Setup removes the assignment. | Check Assignment with TaskUID=22, ResourceUID=7 in saved XML |
| `update_task_duration` | Change "Obtain building permits" (task 7) duration from 4 days (32h) to 6 days (48h). | Check Duration changed to PT48H0M0S in XML |
| `create_milestone` | Add "Foundation Work Complete" milestone (0 days) after task 44 "Strip column piers and foundation forms". | Check new milestone task in Foundations section |
| `add_new_task` | Add "Pre-Inspection Walkthrough" task (2 days) before task 137 "Complete Final Inspections". | Check new task appears before Final Inspections |

## UI Automation Notes

**Task Information Dialog**: Open via the "Link Tasks" toolbar button approach for adding dependencies:
1. Click row N to select it
2. Shift+click row N+1 to multi-select
3. Click **Link** toolbar button (chain icon) at ~(456, 95) in 720p scale → (684, 142) in 1080p

**Toolbar button coordinates** (1280x720 scale, 1920x1080 full resolution):
- Link Tasks: (456, 95) → full: (684, 142)
- Information: (518, 95) → full: (777, 142)
- Assign Resources: (607, 93) → full: (910, 139)
- Calendar: (514, 107) → **WARNING**: this opens "Change Working Calendar" dialog, NOT task info

**NOTE**: When clicking Information at (777, 142) in 1080p, be careful — clicking at y=153+ will hit the Calendar button instead (which opens a working calendar editor, not task properties).

## Timing Reference

- Fresh reset (no cache): ~84s setup + ~11s pre_task = ~95s total
- Cached reset (post_start cache): ~22s restore + ~12s pre_task = ~34s total
- ProjectLibre window appears: typically 5-15s after launch
- Full UI load for 146-task commercial construction project: requires extra 8s wait after window appears

## Known Issues

1. **Java reflective access warnings**: ProjectLibre 1.9.3 emits `WARNING: An illegal reflective access operation has occurred` — these are harmless warnings from Groovy scripting engine and can be ignored.
2. **Window title includes asterisk `*`**: An asterisk (`*`) in the window title means "unsaved changes" in ProjectLibre, which is normal after importing XML.
3. **SourceForge CDN URLs**: The download URL may change; include fallback URLs in the install script.
