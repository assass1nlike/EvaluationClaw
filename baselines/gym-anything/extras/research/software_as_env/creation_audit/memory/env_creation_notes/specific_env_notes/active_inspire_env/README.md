> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# ActivInspire Environment - Implementation Notes

## Environment Status: BLOCKED - Requires Ubuntu 20.04 Base Image

**Summary**: The environment is fully implemented with automated license/welcome dialog handling. However, due to a **fundamental OpenSSL version incompatibility** (ActivInspire compiled against OpenSSL 1.x, Ubuntu 22.04 runtime uses OpenSSL 3.x), the application crashes after the Welcome dialog when the Dashboard attempts SSL/TLS operations.

**This is not a workaround-able issue** - the Qt SSL backend simply cannot function with the version mismatch. Software rendering, libssl1.1 installation, and other workarounds do not resolve this.

**Required Action**: Create an Ubuntu 20.04 base image (`ubuntu-focal-gnome-systemd`) where OpenSSL 1.1 is the native runtime version.

## Application Overview

ActivInspire is Promethean's interactive whiteboard software for education. It creates and manages "flipchart" files (.flipchart) which are actually ZIP archives containing XML and resources.

## Installation Details

### Package Source
- Repository: http://activsoftware.co.uk/linux/repos/ubuntu
- Package: `activinspire_2004-3.5.18-1-amd64.deb` (for Ubuntu Focal/20.04)
- Installation location: `/usr/local/bin/activsoftware/`

### Critical Library Path Fix

ActivInspire bundles Qt6 libraries but they're spread across multiple subdirectories. The default LD_LIBRARY_PATH doesn't find them all.

**Directories containing .so files:**
```
/usr/local/bin/activsoftware/
/usr/local/bin/activsoftware/helperPlugins/
/usr/local/bin/activsoftware/imageformats/
/usr/local/bin/activsoftware/platforms/
/usr/local/bin/activsoftware/printsupport/
/usr/local/bin/activsoftware/sqldrivers/
/usr/local/bin/activsoftware/tls/
/usr/local/bin/activsoftware/xcbglintegrations/
```

**Solution:**
```bash
export LD_LIBRARY_PATH="/usr/local/bin/activsoftware:/usr/local/bin/activsoftware/helperPlugins:/usr/local/bin/activsoftware/imageformats:/usr/local/bin/activsoftware/platforms:/usr/local/bin/activsoftware/printsupport:/usr/local/bin/activsoftware/sqldrivers:/usr/local/bin/activsoftware/tls:/usr/local/bin/activsoftware/xcbglintegrations:$LD_LIBRARY_PATH"
```

## License Dialog Handling

### Dialog Structure
When ActivInspire first runs, it shows a "Promethean License Agreement" dialog with:
- User Name field (optional)
- Activation Key field (optional)
- License text area
- "I accept the terms..." checkbox
- Buttons: "Run Personal Edition...", "Buy Now", "60 Day Trial"

### Button Coordinates (at 1920x1080)
Identified using `ask_cua.py`:
- **Checkbox**: (795, 719)
- **Run Personal Edition**: (840, 746)
- **Buy Now**: (962, 746)
- **60 Day Trial**: (1058, 746)

### Automation Script
```bash
handle_license_dialog() {
    if DISPLAY=:1 wmctrl -l | grep -q "License Agreement"; then
        DISPLAY=:1 xdotool search --name "License Agreement" windowactivate
        sleep 0.5
        DISPLAY=:1 xdotool mousemove 795 719  # checkbox
        DISPLAY=:1 xdotool click 1
        sleep 1
        DISPLAY=:1 xdotool mousemove 840 746  # Run Personal Edition
        DISPLAY=:1 xdotool click 1
    fi
}
```

## Welcome Dialog Handling

After license acceptance, a "Welcome to ActivInspire" dialog appears with:
- Radio buttons for ActivStudio vs ActivPrimary
- Continue button

### Button Coordinates (at 1920x1080)
- **Continue**: (1142, 587)

## Known Issues

### 1. OpenSSL Version Incompatibility
ActivInspire was built with OpenSSL 1.x but Ubuntu 22.04 uses OpenSSL 3.x:
```
qt.tlsbackend.ossl: Incompatible version of OpenSSL (built with OpenSSL 1.x, runtime version is >= 3.x)
```

This breaks TLS/SSL functionality but doesn't prevent basic operation.

### 2. GPU/Graphics Context Crash
The application sometimes crashes with:
```
[ERROR:command_buffer_proxy_impl.cc(140)] ContextResult::kTransientFailure: Failed to send GpuChannelMsg_CreateCommandBuffer
```

This is likely due to VirtualGL or QEMU graphics driver issues.

### 3. LibUSB Warning
Non-fatal warning on startup:
```
LibUsb Init Error -99
```
This is expected in a VM without USB passthrough.

## Configuration Files

### User Configuration
- `/home/ga/.activsoftware/ActivInspire/ActivInspire.conf`
- `/home/ga/.activsoftware/ActivSoftware/ActivSoftware.conf`

Pre-configuring these doesn't prevent the license dialog from appearing on first run.

### Key Settings
```ini
[General]
LicenseAccepted=true
FirstRunComplete=true
ShowDashboardOnStartup=false
ShowWelcome=false
```

## Flipchart File Format

Flipchart files (.flipchart) are ZIP archives containing:
- `content.xml` - Main content definition
- `meta.xml` - Metadata
- `resource/` - Embedded images and media

For verification, extract and parse the XML:
```python
import zipfile
import xml.etree.ElementTree as ET

with zipfile.ZipFile('file.flipchart', 'r') as z:
    content = z.read('content.xml')
    root = ET.fromstring(content)
    # Parse content...
```

## Recommendations for Stable Operation

1. **Use Ubuntu 20.04 base image** - Native compatibility with all dependencies
2. **Install libssl1.1** from Ubuntu Focal archives
3. **Try software rendering**: `QT_QUICK_BACKEND=software`
4. **Increase memory** if crashes occur during heavy operations

## Testing Notes

- Application takes 15-25 seconds to fully start
- License dialog appears ~10 seconds after launch
- Welcome dialog appears immediately after license acceptance
- **Application CRASHES after Welcome dialog on Ubuntu 22.04** - this is not intermittent, it is 100% reproducible

## Detailed Crash Analysis

### Error Sequence from Log
```
qt.tlsbackend.ossl: Incompatible version of OpenSSL (built with OpenSSL 1.x, runtime version is >= 3.x)
qt.network.ssl: The backend "cert-only" does not support QSslKey
qt.network.ssl: Active TLS backend does not support key creation
qt.network.ssl: The backend "cert-only" does not support QSslSocket
qt.network.ssl: The backend named "cert-only" does not support TLS
qt.network.ssl: QSslSocket::connectToHostEncrypted: TLS initialization failed
```

### What This Means
1. ActivInspire bundles Qt6 libraries compiled against OpenSSL 1.x headers
2. Ubuntu 22.04 provides OpenSSL 3.x at runtime
3. Qt detects the version mismatch and falls back to "cert-only" backend
4. The "cert-only" backend doesn't support actual TLS operations
5. The Dashboard (QtWebEngine) requires TLS to function
6. Application crashes when Dashboard tries to make network requests

### Workarounds Attempted (All Failed)
1. **Installing libssl1.1** - Already installed, but Qt checks OpenSSL version at runtime header level
2. **Software rendering** (QT_QUICK_BACKEND=software, LIBGL_ALWAYS_SOFTWARE=1) - Helps with GPU but not SSL
3. **Disabling Dashboard in config** - Config option ignored by application
4. **QTWEBENGINE_DISABLE_GPU** - Doesn't help with SSL
5. **LD_PRELOAD with libssl1.1** - Qt already linked, too late

## Audit Fixes Applied (February 5, 2026)

Multiple independent audits identified issues with the verifiers and export scripts. The following fixes were applied:

### 1. Task Description Corrections
- **Task 2 (add_text_annotation)**: Fixed description to clarify that no pre-existing flipchart exists; user must create a new one first
- **Task 3 (draw_basic_shapes)**: Same fix applied

### 2. Shape Detection Improvements (export_result.sh)
- Changed from keyword matching (`rect`, `circle`) which falsely matched words like "correct", "BoundingRect"
- Now uses proper XML element pattern matching:
  - Rectangles: `<AsRectangle`, `type="Rectangle"`, `shapeType="Rectangle"`
  - Circles: `<AsCircle`, `<AsEllipse`, `type="Circle"`, `type="Ellipse"`

### 3. JSON Output Fixes
- Added `json_bool()` helper function to `task_utils.sh`
- All export scripts now produce valid JSON boolean values (`true`/`false`) instead of shell strings

### 4. Critical Verifier Bug Fix (draw_basic_shapes/verifier.py)
- Fixed pass criteria from `has_rectangle OR has_circle` to `has_rectangle AND has_circle`
- Task now correctly requires BOTH shapes to pass

### 5. VLM Verification Added (All Verifiers)
- Added hybrid verification combining programmatic file checks with VLM visual confirmation
- Verifiers now check for:
  - ActivInspire application visibility
  - Flipchart canvas presence
  - Shapes/text visibility (task-specific)
  - Absence of error dialogs
- Prevents adversarial agents from passing by creating files without using ActivInspire

### 6. Environment Health Checks
- Verifiers now detect when ActivInspire is not visible or has crashed
- VLM checks for error dialogs and crash states
- Partial credit given when VLM unavailable but file evidence is strong

## Date
Notes created: February 5, 2026
Last updated: February 5, 2026 (added audit fixes documentation)
