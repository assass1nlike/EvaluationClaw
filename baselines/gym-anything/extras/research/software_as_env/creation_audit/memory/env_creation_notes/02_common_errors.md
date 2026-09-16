# Common Errors and Solutions

## 0. Docker Hub Rate Limit (docker compose pull fails with 429)

**Error:**
```
ERROR: toomanyrequests: Too Many Requests. Please see https://docs.docker.com/docker-hub/download-rate-limit/
```

**Cause:** Anonymous Docker Hub pulls are rate-limited (~100/6hr per IP). On shared compute this is hit constantly.

**Solution:** Always authenticate before pulling. Store credentials in `config/.dockerhub_credentials` and source them in your post_start hook:
```bash
if [ -f /workspace/config/.dockerhub_credentials ]; then
    source /workspace/config/.dockerhub_credentials
    echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin 2>/dev/null || true
fi
docker compose pull
```
See `07_web_applications_docker.md` for the full pattern and credentials.

---

## 1. Script Permission Denied (MOST COMMON)

**Error:**
```
Permission denied: /workspace/scripts/install_app.sh
```

**Cause:** Scripts don't have execute permission after creation.

**Solution:**
```bash
chmod +x benchmarks/cua_world/environments/<env_name>/scripts/*.sh
chmod +x benchmarks/cua_world/environments/<env_name>/tasks/*/*.sh
```

**Prevention:** Run chmod immediately after creating any .sh file.

---

## 2. Hook Runs But Application Not Installed

**Symptom:** No error, but `which app-name` returns nothing.

**Diagnosis:**
```python
ssh.exec_command('cat /home/<user>/env_setup_pre_start.log')
```

**Common causes:**
- Download URL changed or invalid
- dpkg failed but `apt-get install -f` wasn't in script
- Network timeout during download

---

## 3. Application Starts But Shows Dialogs

**Symptom:** App window appears but first-run dialogs block interaction.

**Observed with:** Google Earth (multiple dialogs), likely GIMP, LibreOffice, etc.

**Solutions:**
1. Pre-create config files to disable first-run wizards
2. Copy settings from `config/` directory in post_start hook
3. Document which dialogs appear for task creators

---

## 4. GNOME Activities Triggers Instead of App Interaction

**Symptom:** When clicking near top-left, GNOME Activities overlay appears instead of interacting with application.

**Cause:** GNOME has a hot corner in top-left that triggers Activities.

**Workarounds:**
- Avoid clicking in top-left quadrant
- Use keyboard shortcuts (`Alt+key`) instead of mouse clicks on menus
- Use `wmctrl -a "Window Title"` to focus windows before interaction

---

## 5. SSH Connection Warning

**Message:**
```
SSH key auth to localhost:XXXX failed (exit 126)
```

**This is normal.** The system falls back to paramiko with password authentication. The warning can be ignored if subsequent connection works.

---

## 6. Desktop Not Ready Timeout

**Error:**
```
Desktop not ready after 120s
```

**Causes:**
- GNOME taking long to initialize
- Systemd services failing
- Previous instance not fully cleaned up

**Solutions:**
- Kill any lingering QEMU processes: `pkill -f "ga_qemu_"`
- Increase timeout if needed
- Check systemd is working in container

---

## 7. Multiple Application Instances Warning

**Dialog:**
```
Another instance of this application is already running
```

**Cause:** Application started by hook and then started again manually or by another script.

**Prevention in scripts:**
```bash
pgrep -f "app-name" || DISPLAY=:1 app-name &
```

---

## 8. Screenshot Capture Fails

**Command:**
```bash
DISPLAY=:1 scrot /tmp/screenshot.png
```

**If this fails, check:**
1. Is scrot installed? (`which scrot`)
2. Is DISPLAY set correctly?
3. Is the display server running?

**Verified working:** scrot works reliably when DISPLAY=:1 is set.

---

## 9. wmctrl Shows No Windows

**Symptom:** `wmctrl -l` returns empty even though app is visible in screenshot.

**Possible causes:**
- Window manager not fully initialized
- App using different display
- App window not yet created (need more wait time)

**Solution:** Add sleep after starting app:
```bash
DISPLAY=:1 app-name &
sleep 5
DISPLAY=:1 wmctrl -l
```

---

## 10. xdotool Keyboard Automation Unreliable

**Symptom:** xdotool key presses don't trigger expected menu actions.

**Observed with:** AstroImageJ menu navigation, File > Import sequences

**Causes:**
- Menu accelerators differ between systems
- Window focus lost between commands
- Timing issues with menu animations

**Solution:** Use command-line arguments or macros instead:
```bash
# BAD - unreliable xdotool menu navigation
DISPLAY=:1 xdotool key alt+f  # File menu
sleep 0.5
DISPLAY=:1 xdotool key i      # Import
# Often fails!

# GOOD - use macro argument for ImageJ-based apps
"$AIJ_PATH" -macro "/tmp/load_data.ijm"
```

---

## 11. Hook Timeout Parameter Not Supported

**Error:**
```
QemuApptainerRunner.exec() got an unexpected keyword argument 'timeout'
```

**Cause:** Base class `exec()` signature doesn't match derived class.

**Solution:** Ensure base class in `src/gym_anything/runtime/runners/base.py` has matching signature:
```python
def exec(self, cmd: str, env: Optional[Dict[str, str]] = None,
         user: Optional[str] = None, use_pty: bool = True,
         timeout: int = 600) -> int:
```

---

## 12. ImageJ/AstroImageJ Macro Commands Differ

**Symptom:** Macro runs in ImageJ but fails in AstroImageJ with "Unrecognized command"

**Example:**
```
Unrecognized command: "Maximize" in line 4
```

**Cause:** AstroImageJ is based on ImageJ but has different/missing commands.

**Solution:** Test macros in the actual application and use only supported commands:
```javascript
// Works in both ImageJ and AstroImageJ:
run("Image Sequence...", "open=/path/to/dir sort use");
setSlice(1);
wait(5000);

// May NOT work in AstroImageJ:
run("Maximize");  // Not a valid command
```

---

## 13. Large Downloads Timeout During Install

**Symptom:** Installation script fails partway through downloading large files (>1GB).

**Observed with:** WASP-12b transit data (4.3GB), medical imaging datasets

**Solution:**
1. Increase wget timeout:
```bash
wget --timeout=300 "$URL" -O output.tar.gz
```

2. Cache large downloads at install time, not task setup:
```bash
# In install script (runs once):
CACHED_DATA="/opt/fits_samples/large_dataset.tar.gz"
if [ ! -f "$CACHED_DATA" ]; then
    wget "$URL" -O "$CACHED_DATA"
fi

# In task setup (runs each time):
if [ -f "$CACHED_DATA" ]; then
    tar -xzf "$CACHED_DATA" -C "$DATA_DIR"
fi
```

3. Set appropriate thresholds for partial downloads:
```bash
# Accept partial data if most files present
if [ "$FILE_COUNT" -lt 100 ]; then
    echo "ERROR: Download incomplete"
    exit 1
elif [ "$FILE_COUNT" -lt 200 ]; then
    echo "WARNING: Some files missing, continuing anyway"
fi
```

---

# Android-Specific Errors

---

## 14. Emulator Disk Space Error

**Error:**
```
FATAL | Your device does not have enough disk space to run avd: `gym_android_34`
```

**Cause:** Android emulator work directories accumulate in `/tmp/ga_avd_*/` and can use 6-11GB each.

**Solution:**
```bash
# List old work directories
du -sh /tmp/ga_avd_* 2>/dev/null

# Clean up (safe if no emulators running)
rm -rf /tmp/ga_avd_*/

# Check disk space
df -h /tmp
```

---

## 15. Hook Path Duplication (sh sh /path)

**Error:**
```
sh: sh: not found
```
or script doesn't execute.

**Cause:** Hook path in env.json has `sh` prefix, but framework also adds `sh` for Android.

**Bad:**
```json
"hooks": {
  "post_start": "sh /sdcard/tasks/task/script.sh"
}
```

**Good:**
```json
"hooks": {
  "post_start": "/sdcard/tasks/task/script.sh"
}
```

---

## 16. Android Hook Timeout

**Error:**
```
post_start hook failed: Command '...' timed out after 60 seconds
```

**Cause:** Default exec timeout was 60s, but Android games can take 100+ seconds to load.

**Solution:** Framework now uses 180s timeout for Android hooks automatically. If you still hit this:
1. Reduce sleep times in your script where possible
2. Use caching/checkpointing for loaded states

---

## 17. APK Installation Failure via pm install

**Error:**
```
Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]
```
or very slow installation.

**Cause:** Using `pm install` from `/sdcard/` for large APKs is slow and unreliable.

**Solution:** Use the `apks` field in env.json for automatic `adb install`:
```json
{
  "apks": [
    "benchmarks/cua_world/environments/app_env/scripts/apks/app.apk"
  ]
}
```

---

## 18. Immersive Mode Notification Blocking

**Symptom:** A notification "Swipe down to exit fullscreen" appears and blocks UI elements.

**Cause:** Android's immersive mode confirmation dialog.

**Solution:** The AVD runner now automatically disables this. If you see this issue:
```bash
# Manually disable via ADB
adb shell settings put secure immersive_mode_confirmations confirmed
adb shell settings put global policy_control "immersive.full=*"
```

---

## 19. ADB Device Not Found

**Error:**
```
adb: device 'emulator-5556' not found
```

**Causes:**
- Emulator crashed or was killed
- Wrong port number
- ADB server needs restart

**Solutions:**
```bash
# List connected devices
~/.cache/gym-anything/android-sdk/platform-tools/adb devices

# Restart ADB server
~/.cache/gym-anything/android-sdk/platform-tools/adb kill-server
~/.cache/gym-anything/android-sdk/platform-tools/adb start-server
```

---

## 20. UI Dump Returns Empty

**Error:**
```
UI dump is empty or too small
```

**Causes:**
- Screen is in transition (loading, animation)
- App uses custom rendering (games, OpenGL)
- uiautomator service not running

**Solutions:**
1. Add sleep before dump:
```bash
sleep 2
uiautomator dump /sdcard/ui_dump.xml
```

2. For games, dump at stable screens (menu, game over):
```bash
# Wait for game over screen
sleep 3
uiautomator dump /sdcard/ui_dump.xml
```

3. Some games use custom rendering - UI dump may not capture game elements.

---

## 21. Wrong Tap Coordinates

**Symptom:** Taps don't hit expected UI elements.

**Cause:** Coordinates were calculated for different resolution or device.

**Debug:**
```bash
# Get actual device resolution
adb shell wm size

# Take screenshot and dump UI
adb exec-out screencap -p > /tmp/debug.png
adb shell uiautomator dump /sdcard/ui_dump.xml
adb pull /sdcard/ui_dump.xml /tmp/

# Find bounds in UI dump
grep -o 'bounds="[^"]*"' /tmp/ui_dump.xml
```

**Calculate center:**
- bounds="[744,592][975,718]"
- Center X: (744 + 975) / 2 = 860
- Center Y: (592 + 718) / 2 = 655

---

## 22. VNC Server Not Starting

**Warning:**
```
VNC server may not have started - continuing anyway
```

**Cause:** DroidVNC-NG requires user interaction to start sometimes.

**Workaround:** This is non-fatal. You can still:
1. Take screenshots via `adb exec-out screencap`
2. Use the environment without VNC viewing
3. Connect via ADB for debugging

---

# Lessons Learned from Environment Creation

> **See also `10_cross_cutting_patterns.md`** for 16 generalizable patterns distilled from 80+ environments — covering service readiness, dialog suppression, process detection, verification anti-gaming, Docker gotchas, snap packages, coordinate scaling, and more. The errors below are specific examples; the cross-cutting doc provides the general principles.

The following errors were discovered during the creation of the Blender 3D environment and serve as cautionary examples.

---

## 23. Using Procedural/Toy Data Instead of Real Data (CRITICAL)

**Mistake:** Creating simple procedurally-generated scenes using application APIs instead of downloading official demo files.

**Example of what NOT to do:**
```python
# BAD - Procedurally generated "toy data"
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
bpy.ops.mesh.primitive_sphere_add(radius=1, location=(-3, 0, 1))
bpy.ops.wm.save_as_mainfile(filepath="sample_scene.blend")
```

**Why this is wrong:**
- These are "handwritten toy scenes" - not realistic data
- They don't capture the complexity of real-world 3D scenes
- Verification against toy data is meaningless for benchmarking

**Correct approach:**
```bash
# GOOD - Download official demo files
wget https://download.blender.org/demo/test/BMW27.blend.zip
wget https://download.blender.org/demo/test/classroom.zip
wget https://download.blender.org/demo/splash/blender-4.0-splash.blend
```

**Sources for real data:**
- Blender: https://download.blender.org/demo/
- Medical imaging: Public datasets from research repositories
- Astronomy: NASA archives, survey data releases

---

## 24. Non-Robust Verification (Easily Gameable)

**Mistake:** Writing verifiers that only check basic file properties.

**Example of what NOT to do:**
```python
# BAD - Simple verification, easily gamed
def verify_render(traj, env_info, task_info):
    if result.get('output_exists') and result.get('file_size_kb') > 50:
        return {"passed": True, "score": 100, "feedback": "File exists"}
```

**Why this is wrong:**
- Passes if agent does nothing and file pre-exists
- Passes if agent creates any file > 50KB (could be garbage)
- No verification that actual render happened
- No VLM visual verification

**Correct approach - Multi-signal verification:**
```python
# GOOD - 8+ criteria, VLM verification, "do nothing" detection
def verify_render(traj, env_info, task_info):
    score = 0

    # Criterion 1: File exists (15 pts)
    # Criterion 2: File was CREATED during task (15 pts) - catches pre-existing
    # Criterion 3: File size reasonable (10 pts)
    # Criterion 4: Dimensions correct (10 pts)
    # Criterion 5: Application was running (10 pts)
    # Criterion 6: Render actually performed (15 pts) - render time > 0
    # Criterion 7: VLM confirms 3D content (15 pts)
    # Criterion 8: VLM confirms not just UI screenshot (10 pts)

    # "Do nothing" detection
    if not file_created and not file_modified:
        score = min(score, 20)  # Cap score

    # Key criteria must ALL be met
    key_criteria_met = file_created and render_performed and (vlm_verified or dimensions_ok)
    passed = score >= 60 and key_criteria_met
```

**Always include test cases:**
```python
# Test that these FAIL:
# 1. Agent did nothing
# 2. File suspiciously small
# 3. Pre-existing file not modified
# 4. Wrong parameters
```

---

## 25. Forgetting to Add VLM Verification to ALL Tasks

**Mistake:** Adding VLM verification to one task but forgetting other tasks in the same environment.

**Example:** Updated `render_basic_scene` verifier with VLM but forgot `add_sphere_to_scene`.

**Why this matters:**
- Inconsistent verification quality across tasks
- Some tasks become gameable while others aren't
- Creates confusion about verification standards

**Correct approach:**
- When updating verification patterns, update ALL tasks in the environment
- Create a checklist of tasks and verify each one has:
  - [ ] VLM visual verification
  - [ ] "Do nothing" detection
  - [ ] Multiple independent signals
  - [ ] Test cases for failure modes

---

## 26. GPU Rendering Misconceptions in QEMU/Virtio

**Mistake:** Assuming Virtio GPU provides GPU compute for rendering engines.

**What actually happens:**
```
--- GPU CONFIGURATION ---
compute_device_type: "NONE"  # No GPU compute available!
devices: [{"name": "AMD EPYC CPU", "type": "CPU", "use": true}]

--- GPU HARDWARE ---
00:02.0 VGA compatible controller: Red Hat, Inc. Virtio GPU (rev 01)
```

**The confusion:**
- Virtio GPU IS working (for display/OpenGL)
- But Cycles/path-tracing renderers need CUDA/HIP/OpenCL
- These require actual GPU passthrough, not Virtio

**What Virtio GPU provides:**
- ✅ Display output to VNC
- ✅ OpenGL for application UI rendering
- ✅ Basic 3D acceleration for viewports
- ❌ GPU compute for Cycles/path-tracing (uses CPU instead)

**Correct understanding:**
```bash
# Virtio GPU = Display acceleration (works)
# Cycles GPU rendering = Needs CUDA/HIP/OpenCL (falls back to CPU)

# This is EXPECTED and CORRECT behavior in QEMU
# Renders will use CPU, which is fine for testing
```

**Documentation should clarify:**
- "GPU support" means display acceleration via Virtio
- Render engines will use CPU in virtualized environments
- For true GPU rendering, need GPU passthrough (not typical for CI/testing)
