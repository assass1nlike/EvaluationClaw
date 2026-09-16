# Android Environment Creation Guide

This guide covers creating environments for Android applications using the AVD (Android Virtual Device) emulator in gym_anything.

## Overview

Android environments differ from Linux environments in several key ways:

| Aspect | Linux (QEMU) | Android (AVD) |
|--------|--------------|---------------|
| **Runner** | QEMUApptainerRunner | AVDApptainerRunner |
| **Mounts** | Bind mounts (static) | ADB push (dynamic) |
| **Communication** | SSH / container exec | ADB shell commands |
| **Screenshot** | X11 screenshot tool | screencap → pull PNG |
| **Input** | X11 / keyboard driver | ADB input commands |
| **Installation** | Package manager / apt | APK install via pm |
| **State export** | File system snapshots | uiautomator XML dump |

## Directory Structure

```
benchmarks/cua_world/environments/<app>_env/
├── env.json                    # Environment configuration
├── scripts/
│   ├── setup_<app>.sh         # Post-start hook (installs app, initial setup)
│   └── apks/                   # APK files for the application
│       └── <app>.apk          # Main application APK
├── tasks/
│   └── <task_name>/
│       ├── task.json          # Task specification
│       ├── setup_task.sh      # Pre-task hook
│       ├── export_result.sh   # Post-task hook (exports verification data)
│       └── verifier.py        # Verification logic
├── artifacts/                  # Test outputs (episodes, screenshots)
└── test_<app>.py              # Test script
```

## env.json Configuration

### Required Fields

```json
{
  "id": "example.<app>_env@0.1",
  "version": "0.1",
  "base": "android-avd-34",
  "description": "Description of your environment",
  "avd": {
    "variant": "google_apis_playstore"
  },
  "resources": {
    "cpu": 4,
    "mem_gb": 6,
    "gpu": 0,
    "net": true
  },
  "observation": [
    {
      "type": "rgb_screen",
      "fps": 10,
      "resolution": [1080, 2400],
      "inline": false
    }
  ],
  "action": [
    {"type": "mouse"},
    {"type": "keyboard"}
  ],
  "apks": [
    "benchmarks/cua_world/environments/<app>_env/scripts/apks/<app>.apk"
  ],
  "mounts": [
    {
      "source": "benchmarks/cua_world/environments/<app>_env/tasks",
      "target": "/sdcard/tasks",
      "mode": "ro"
    }
  ],
  "hooks": {
    "post_start": "/sdcard/tasks/<task_name>/launch_app.sh"
  }
}
```

### APK Installation (Important!)

**Use the `apks` field** for automatic APK installation. This uses `adb install` which:
- Streams the APK directly to the device (faster than copying to /sdcard)
- Works with large APKs (200MB+)
- Handles installation automatically during environment startup

```json
{
  "apks": [
    "benchmarks/cua_world/environments/my_app_env/scripts/apks/my_app.apk"
  ]
}
```

**Do NOT use `pm install` from /sdcard** for large APKs - it's much slower and can fail.
```

### AVD Variants

| Variant | Description | Play Store |
|---------|-------------|------------|
| `google_apis` | Google APIs, no Play Store | No |
| `google_apis_playstore` | Google APIs with Play Store | Yes |
| `default` | AOSP (vanilla Android) | No |

### Base Images

| Base | Android Version | API Level |
|------|-----------------|-----------|
| `android-avd-34` | Android 14 | 34 |
| `android-avd-35` | Android 15 | 35 |

### Hook Timeouts

Android hooks have a **180-second timeout** (vs 60s default). This is important because:
- Games can take 60+ seconds to load
- Initial setup (age verification, tutorials) adds time
- Network operations may be slow

If your setup script needs more time, the framework will wait up to 180 seconds.

### Immersive Mode (Fullscreen Apps)

The framework automatically disables immersive mode notifications by setting:
```bash
settings put secure immersive_mode_confirmations confirmed
settings put global policy_control "immersive.full=*"
```

This prevents the "Swipe down to exit fullscreen" notification from blocking UI automation.

## Scripts

### Shell Shebang

Android uses a different shell. Always use:

```bash
#!/system/bin/sh
```

NOT `#!/bin/bash` (bash is not available on Android).

### Setup Script (post_start)

```bash
#!/system/bin/sh
# Post-start setup script for <App> environment

echo "=== Setting up <App> Environment ==="

# Wait for system to be ready
sleep 5

# Press Home to ensure we're at home screen
input keyevent KEYCODE_HOME
sleep 2

# Package name for your app
PACKAGE="com.example.app"

# Check if app is installed
if pm list packages | grep -q "$PACKAGE"; then
    echo "App already installed"
else
    # Install from APK
    if [ -f /sdcard/scripts/apks/app.apk ]; then
        pm install -r /sdcard/scripts/apks/app.apk
    else
        echo "ERROR: APK not found"
        exit 1
    fi
fi

# Launch the app
monkey -p $PACKAGE -c android.intent.category.LAUNCHER 1 2>/dev/null

sleep 3
echo "=== Setup completed ==="
```

### Task Setup Script (pre_task)

```bash
#!/system/bin/sh
# Pre-task setup script

echo "=== Setting up task ==="

# Go to home screen
input keyevent KEYCODE_HOME
sleep 1

# Launch app
monkey -p com.example.app -c android.intent.category.LAUNCHER 1
sleep 2

# Navigate to correct screen, clear state, etc.

echo "=== Task setup completed ==="
```

### Export Script (post_task)

```bash
#!/system/bin/sh
# Export verification data

echo "=== Exporting task result ==="

# Take screenshot
screencap -p /sdcard/final_screenshot.png

# Dump UI hierarchy for verification
uiautomator dump /sdcard/ui_dump.xml 2>/dev/null

if [ -f /sdcard/ui_dump.xml ]; then
    echo "UI dump created"
    ls -la /sdcard/ui_dump.xml
else
    echo "Warning: UI dump failed"
fi

echo "=== Export completed ==="
```

## Common Android Commands

### ADB Input Commands

| Action | Command |
|--------|---------|
| Tap at (x,y) | `input tap x y` |
| Swipe from A to B | `input swipe x1 y1 x2 y2 [duration_ms]` |
| Long press | `input swipe x y x y 1000` |
| Type text | `input text "your text"` |
| Press key | `input keyevent KEYCODE_NAME` |

### Common Key Events

| Key | Keycode |
|-----|---------|
| Home | `KEYCODE_HOME` |
| Back | `KEYCODE_BACK` |
| Enter | `KEYCODE_ENTER` |
| Delete | `KEYCODE_DEL` |
| Menu | `KEYCODE_MENU` |
| Volume Up | `KEYCODE_VOLUME_UP` |
| Volume Down | `KEYCODE_VOLUME_DOWN` |

### Package Management

| Action | Command |
|--------|---------|
| List packages | `pm list packages` |
| Check if installed | `pm list packages \| grep "package.name"` |
| Install APK | `pm install -r /path/to/app.apk` |
| Uninstall | `pm uninstall package.name` |

### App Launch

```bash
# Method 1: Using monkey (simplest)
monkey -p com.example.app -c android.intent.category.LAUNCHER 1

# Method 2: Using am start
am start -n com.example.app/.MainActivity

# Method 3: Using intent
am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER com.example.app
```

## Verification

### Using uiautomator Dump

The primary verification method is parsing the UI accessibility tree:

```python
def verify_task(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')

    # Copy UI dump from device
    temp_dir = tempfile.mkdtemp()
    local_dump = os.path.join(temp_dir, "ui_dump.xml")

    try:
        copy_from_env("/sdcard/ui_dump.xml", local_dump)

        with open(local_dump, 'r') as f:
            ui_xml = f.read()

        # Parse XML for expected content
        # Look in text attributes, content-desc, resource-id, etc.
        if 'expected_text' in ui_xml:
            return {"passed": True, "score": 100, "feedback": "Success!"}

        return {"passed": False, "score": 0, "feedback": "Expected text not found"}

    except Exception as e:
        return {"passed": False, "score": 0, "feedback": f"Error: {e}"}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
```

### Extracting Data from UI Dump

```python
import re

def extract_text_fields(ui_xml):
    """Extract all text attributes from UI dump."""
    return re.findall(r'text="([^"]*)"', ui_xml)

def extract_content_desc(ui_xml):
    """Extract all content-desc attributes."""
    return re.findall(r'content-desc="([^"]*)"', ui_xml)

def find_by_resource_id(ui_xml, resource_id_pattern):
    """Find nodes with matching resource-id."""
    pattern = f'resource-id="{resource_id_pattern}"[^>]*text="([^"]*)"'
    return re.findall(pattern, ui_xml, re.IGNORECASE)
```

## APK Acquisition

### Options

1. **Pre-packaged APK**: Place APK in `scripts/apks/`
2. **Play Store**: Use `google_apis_playstore` variant and install via VNC
3. **F-Droid**: Download open-source APKs
4. **APKMirror/APKPure**: For proprietary apps (legal considerations apply)

### Play Store Installation (Manual)

1. Use VNC to connect to the emulator
2. Open Play Store on the device
3. Sign in with a Google account
4. Search and install the app
5. The app will persist in checkpoints

## Challenges and Solutions

### Real-Time Games (e.g., Subway Surfers)

For games with continuous action:

- **Loading time**: Games can take 40-60 seconds to load. Use adequate `sleep` in your hook scripts.
- **Swipe actions**: Use `input swipe x1 y1 x2 y2 duration_ms` for gesture controls:
  ```bash
  # Swipe up (jump)
  input swipe 540 1600 540 1000 150

  # Swipe left (change lane)
  input swipe 700 1200 300 1200 150

  # Swipe down (roll/slide)
  input swipe 540 1000 540 1600 150
  ```
- **Verification timing**: Verify at game over screens where UI is stable, not during gameplay.
- **Score extraction**: Use UI dump to find score-related text fields.

### Age Verification Dialogs

Many games have age verification that requires multiple taps:

```bash
# Example: Incrementing age picker (right arrow at 900, 1400)
# Tap 25 times to set age to 25
for i in $(seq 1 25); do
    input tap 900 1400
done
sleep 2

# Tap confirm button
input tap 540 1600
```

### Tutorial Screens

Games often have tutorials that block interaction:

```bash
# Tap through tutorial screens
input tap 540 1400  # "Next" button
sleep 2
input tap 540 1400  # Another "Next"
sleep 2
input tap 540 2100  # "Start" button
```

### Dynamic Content

For apps with changing content:

- Use multiple verification patterns
- Check for partial matches
- Give partial credit for progress

### First-Run Dialogs

Handle initial setup screens:

```bash
# Dismiss dialogs
input keyevent KEYCODE_BACK
sleep 1

# Tap "Accept" or "OK" areas (usually bottom of screen)
input tap 540 2100
sleep 1

# Tap "Got it" for fullscreen notifications (usually right side)
input tap 860 655
sleep 1
```

### Network Dependencies

For apps requiring network:

```json
{
  "resources": {
    "net": true
  }
}
```

### Disk Space Issues

Android emulators use significant disk space (~6GB+ work directory). If you see:
```
FATAL | Your device does not have enough disk space
```

Clean up old work directories:
```bash
# List old AVD work directories
du -sh /tmp/ga_avd_* 2>/dev/null

# Clean up (be careful not to delete running emulators)
rm -rf /tmp/ga_avd_*/
```

## Interactive Debugging

### Connecting to Running Emulator

When developing Android environments, interactive debugging is essential:

```bash
# Set ADB path
export ADB=~/.cache/gym-anything/android-sdk/platform-tools/adb

# List connected devices
$ADB devices -l

# Connect to a specific emulator (e.g., emulator-5556)
$ADB -s emulator-5556 shell
```

### Taking Screenshots During Development

```bash
# Take screenshot and save locally
$ADB -s emulator-5556 exec-out screencap -p > /tmp/debug_screenshot.png
```

### Getting UI Hierarchy for Finding Coordinates

```bash
# Dump UI to device
$ADB -s emulator-5556 shell uiautomator dump /sdcard/ui_dump.xml

# Pull to local machine
$ADB -s emulator-5556 pull /sdcard/ui_dump.xml /tmp/ui_dump.xml

# View the dump
cat /tmp/ui_dump.xml | grep -o 'bounds="[^"]*"' | head -20
```

### Finding Exact Tap Coordinates

From the UI dump, find bounds like `bounds="[744,592][975,718]"`:
- Format: `[left,top][right,bottom]`
- Center X: (744 + 975) / 2 = 860
- Center Y: (592 + 718) / 2 = 655
- Tap command: `input tap 860 655`

### Testing Input Commands

```bash
# Tap at coordinates
$ADB -s emulator-5556 shell input tap 540 1200

# Swipe (for games like Subway Surfers)
$ADB -s emulator-5556 shell input swipe 540 1600 540 1000 150

# Type text
$ADB -s emulator-5556 shell input text "hello"

# Press key
$ADB -s emulator-5556 shell input keyevent KEYCODE_BACK
```

### Monitoring Logs

```bash
# View Android logs
$ADB -s emulator-5556 logcat -d | tail -100

# Filter by app
$ADB -s emulator-5556 logcat -d | grep "com.example.app"
```

## Testing

### Test Script Template

```python
#!/usr/bin/env python3
import os
os.environ["ADB_MDNS"] = "0"

from gym_anything.api import from_config

def test_environment():
    env = from_config('benchmarks/cua_world/environments/<app>_env', task_id='<task_name>')
    try:
        obs = env.reset(seed=42)
        print(f"Environment started!")

        # Test actions
        action = {"mouse": {"left_click": [540, 1200]}}
        obs, reward, done, info = env.step([action])
        print(f"Step completed: reward={reward}, done={done}")

    finally:
        env.close()

if __name__ == "__main__":
    test_environment()
```

### Interactive Testing

```bash
# Start in interactive mode
python benchmarks/cua_world/environments/<app>_env/test_<app>.py --interactive

# Connect via VNC to observe
# VNC port is printed at startup
```

## Example: Subway Surfers

The `subway_surfers_env` demonstrates a gaming environment:

- Real-time endless runner game
- Swipe-based controls
- Score verification via UI dump
- Handles initial dialogs and tutorials

Key files:
- `env.json`: Uses `google_apis_playstore` for Play Store access
- `scripts/setup_subway_surfers.sh`: Installs and launches game
- `tasks/score_1000_points/`: Task to achieve 1000+ points
- `verifier.py`: Extracts score from UI dump

## Advanced Android Lessons (from real environment builds)

The following sections document practical lessons learned from building real Android environments (e.g., Flight Crew View / FLICA). These go beyond the basics above and cover edge cases you **will** encounter.

---

### Split APK / App Bundle Installation

Many modern Android apps are distributed as **App Bundles** (AAB) which produce split APKs. A single `pm install` won't work — you get multiple files like:

```
com.example.app.apk          # Base APK
config.arm64_v8a.apk         # CPU architecture split
config.en.apk                # Language split
config.xxhdpi.apk            # Screen density split
```

**You must use `pm install-create` / `pm install-write` / `pm install-commit` sessions:**

```bash
# 1. Copy APKs to /data/local/tmp (SELinux blocks pm install from /sdcard)
INSTALL_DIR="/data/local/tmp/app_install"
mkdir -p "$INSTALL_DIR"
cp /sdcard/scripts/apks/*.apk "$INSTALL_DIR/"
chmod 644 "$INSTALL_DIR"/*.apk

# 2. Create an install session
SESSION_ID=$(pm install-create -r 2>&1 | grep -o '[0-9]*')

# 3. Write each APK into the session
BASE_SIZE=$(wc -c < "$INSTALL_DIR/com.example.app.apk")
pm install-write -S "$BASE_SIZE" "$SESSION_ID" base "$INSTALL_DIR/com.example.app.apk"

for SPLIT_APK in "$INSTALL_DIR"/config.*.apk; do
    SPLIT_NAME=$(basename "$SPLIT_APK" .apk)
    SPLIT_SIZE=$(wc -c < "$SPLIT_APK")
    pm install-write -S "$SPLIT_SIZE" "$SESSION_ID" "$SPLIT_NAME" "$SPLIT_APK"
done

# 4. Commit the session
pm install-commit "$SESSION_ID"

# 5. Cleanup
rm -rf "$INSTALL_DIR"
```

**Key points:**
- APKs in `/sdcard/` are blocked by SELinux for `pm install-write`; always copy to `/data/local/tmp/` first.
- The `-S` flag requires the exact file size in bytes.
- If any split is missing (e.g., wrong architecture), the commit will fail.
- To download split APKs, use sites like APKCombo or Aptoide that offer XAPK/split bundles (not just single APKs).

---

### Special Characters in `input text`

`adb shell input text` treats `#`, `&`, `(`, `)`, and other shell special characters as literal shell metacharacters. **You must use URL-style percent encoding:**

| Character | Encoding |
|-----------|----------|
| `#` | `%23` |
| `&` | `%26` |
| `<space>` | `%s` |
| `(` | `%28` |
| `)` | `%29` |
| `@` | Works as-is in most cases |
| `.` | Works as-is |

**Example:**

```bash
# Password is #Aa123456aA
# WRONG: input text "#Aa123456aA"       # Shell treats # as comment
# WRONG: input text '\#Aa123456aA'      # Escaping doesn't always work
# RIGHT:
input text '%23Aa123456aA'
```

Also note: `input text` doesn't support newlines or multi-line input. Use `input keyevent` for special keys.

---

### App State Persistence vs. Clean Reset

Android apps persist state in different layers. Understanding this is critical for setup scripts:

| Method | What it does | When to use |
|--------|-------------|-------------|
| `am force-stop <pkg>` | Kills process only. App data/login state **persists**. | Re-launch app from same state |
| `pm clear <pkg>` | Wipes ALL app data (login, preferences, cache) | True fresh start, as if just installed |
| Uninstall + reinstall | Removes everything including APK | Only when APK version matters |

**Important:** If your app has a login flow, `am force-stop` + relaunch will keep the user logged in. `pm clear` will force re-login. Choose the right one for your task setup.

---

### UI-Dump-Based Conditional Logic in Shell Scripts

The most powerful technique for robust setup scripts is **using `uiautomator dump` to check what screen you're on**, then branching accordingly. This handles non-deterministic app behavior (network delays, cached sessions, variable dialogs):

```bash
#!/system/bin/sh
# Dump current UI state
uiautomator dump /sdcard/screen_check.xml 2>/dev/null
sleep 1

UI_CONTENT=""
if [ -f /sdcard/screen_check.xml ]; then
    UI_CONTENT=$(cat /sdcard/screen_check.xml)
fi

# Branch based on what screen we're on
if echo "$UI_CONTENT" | grep -q "expected_text_for_screen_A"; then
    echo "On Screen A - doing action A..."
    input tap 540 1200
elif echo "$UI_CONTENT" | grep -q "expected_text_for_screen_B"; then
    echo "On Screen B - doing action B..."
    input tap 540 1600
else
    echo "Unknown screen - trying fallback..."
    input keyevent KEYCODE_BACK
fi

rm -f /sdcard/screen_check.xml
```

**Key patterns to grep for in UI dumps:**
- `content-desc="Button Text"` — accessibility descriptions (most reliable)
- `text="Visible Text"` — text shown in EditText fields
- `class="android.widget.Button"` — element types
- `clickable="true"` — interactive elements
- `selected="true"` / `checked="true"` — state of checkboxes/tabs

**Why this matters:** Blind tapping at coordinates fails when the app takes variable time to load, shows different screens based on cached state, or has network-dependent content. UI dump checks make scripts idempotent and robust.

---

### Keyboard Handling

The soft keyboard causes many issues in Android automation:

1. **Keyboard covers buttons:** When typing in a field, the keyboard often covers the submit button. You can't tap it until the keyboard is dismissed.

2. **Dismissing the keyboard:**
   ```bash
   # Method 1: Press BACK (dismisses keyboard without navigating back)
   input keyevent KEYCODE_BACK

   # Method 2: Press ENTER (may submit form or move to next field)
   input keyevent KEYCODE_ENTER

   # WARNING: BACK can also navigate away if keyboard is already hidden!
   # Always check screen state after using BACK.
   ```

3. **Navigating between fields:**
   ```bash
   # TAB moves focus to the next field
   input keyevent KEYCODE_TAB

   # This is safer than tapping the next field, which might
   # have shifted position due to keyboard/scrolling
   ```

4. **Form submission pattern:**
   ```bash
   # Fill field 1
   input tap 540 1304          # Tap field
   sleep 1
   input text "value1"

   # Move to field 2
   input keyevent KEYCODE_TAB
   sleep 0.5
   input text "value2"

   # Dismiss keyboard BEFORE tapping submit button
   input keyevent KEYCODE_BACK
   sleep 1

   # Now tap submit (button is visible)
   input tap 540 1540
   ```

---

### Emulator Snapshot Limitations

If the AVD emulator is started with the `-read-only` flag (which gym_anything does by default), **you cannot save snapshots**:

```
KO: Snapshot save is disabled because "-read-only" was specified
```

**Workaround:** Your setup scripts must handle the full app initialization flow every time. This means:
- APK installation check (skip if already installed)
- App launch
- Login/authentication flow
- Navigation to the correct starting screen

Use a **shared helper script** (e.g., `login_helper.sh`) that all tasks can call, rather than duplicating login logic in every task's `setup_task.sh`.

---

### Emulator Console Access

To send commands to the emulator console (not the Android shell), use `nc` (netcat):

```bash
# Read the auth token
AUTH_TOKEN=$(cat /tmp/.emulator_console_auth_token)

# Send commands
printf "auth $AUTH_TOKEN\navd name\nquit\n" | nc localhost 5556
```

Note: `telnet` is not available on many systems; `nc` is the reliable alternative.

---

### Runtime Permission Pre-granting

Android apps request permissions at runtime (camera, location, notifications, etc.). These dialogs can block automation. **Pre-grant all permissions in your setup script:**

```bash
PACKAGE="com.example.app"

# Grant all common permissions upfront
pm grant $PACKAGE android.permission.ACCESS_FINE_LOCATION 2>/dev/null
pm grant $PACKAGE android.permission.ACCESS_COARSE_LOCATION 2>/dev/null
pm grant $PACKAGE android.permission.POST_NOTIFICATIONS 2>/dev/null
pm grant $PACKAGE android.permission.READ_CALENDAR 2>/dev/null
pm grant $PACKAGE android.permission.WRITE_CALENDAR 2>/dev/null
pm grant $PACKAGE android.permission.READ_CONTACTS 2>/dev/null
pm grant $PACKAGE android.permission.CAMERA 2>/dev/null
pm grant $PACKAGE android.permission.RECORD_AUDIO 2>/dev/null
pm grant $PACKAGE android.permission.READ_EXTERNAL_STORAGE 2>/dev/null
pm grant $PACKAGE android.permission.WRITE_EXTERNAL_STORAGE 2>/dev/null
```

The `2>/dev/null` suppresses errors for permissions the app doesn't declare. Not all permissions can be pre-granted (some require user interaction), but most runtime permissions can be.

---

### Tab Navigation and Content Descriptions

Many Android apps use tabs (LOG IN / CREATE ACCOUNT, etc.). Important notes:

- **Tabs are identified by `content-desc`**, not `text`. Example:
  ```xml
  content-desc="LOG IN&#10;Tab 1 of 2"
  content-desc="CREATE ACCOUNT&#10;Tab 2 of 2"
  ```
- The `&#10;` is a newline character in the XML. When grepping, search for the tab label without the "Tab X of Y" suffix.
- `selected="true"` indicates the currently active tab.
- Tapping a tab changes the content below it but the tab bar coordinates stay the same.

---

### Coordinate Systems

Coordinates in `input tap` and UI dumps use **actual screen pixels** (not density-independent pixels):

- Screen resolution: typically `1080x2400` for modern phones
- Bounds format in UI dump: `[left,top][right,bottom]`
- Center of bounds: `((left+right)/2, (top+bottom)/2)`
- Status bar: typically 128px tall (bounds `[0,0][1080,128]`)
- Navigation bar: typically 63px tall at bottom (bounds `[0,2337][1080,2400]`)
- Usable area: `[0,128]` to `[1080,2337]`

**Scrolling shifts coordinates!** After a scroll, the same element may be at different Y coordinates. Always re-dump the UI after scrolling to get updated bounds.

---

### Apps Requiring Account Creation / Login

For apps that require authentication (not just local-only apps):

1. **Create the account manually first** using interactive ADB commands or VNC during development.
2. **Use `input text` to type credentials** in setup scripts (with proper encoding for special chars).
3. **Handle the "already logged in" case** — the app may remember the session. Your script must work whether the user is logged in or not.
4. **Email verification** may be required for some apps. This is a manual step that must be done once during development. After verification, the account persists across reinstalls (server-side).
5. **Store credentials in the login helper script** (not in task scripts) so they're defined in one place.

**Recommended pattern**: Create a shared `login_helper.sh` that:
- Force-stops the app
- Relaunches it
- Uses UI dumps to detect the current screen
- Branches to handle: already logged in, welcome screen, login screen, etc.
- All task `setup_task.sh` scripts call this helper

---

### Network-Dependent Apps

Apps requiring internet access have extra considerations:

- Set `"net": true` in `resources` in env.json
- **First launch may be slow** due to network initialization, Firebase setup, etc. Use generous `sleep` values (10-15 seconds).
- **Network errors are transient** — if login fails, the setup script should retry or check if it's a network issue vs. wrong credentials.
- The emulator's network goes through the host. If the host has firewall restrictions, some app features may not work.

---

## Registration

Add to `constants.py`:

```python
# Android <App> environment
try:
    <app>_tasks = [x for x in os.listdir('benchmarks/cua_world/environments/<app>_env/tasks') if x.find('.')==-1]
except FileNotFoundError:
    <app>_tasks = ['default_task']

# In ENV_TASK_SPLITS:
'<app>_env': {
    'all' : <app>_tasks,
    'train' : <app>_tasks,
    'test' : [],
},
```
