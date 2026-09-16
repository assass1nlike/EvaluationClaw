> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# PEBL Environment - Creation Notes

## Installation Quirks

### Building from Source is Required
PEBL 2.3 AppImage requires GLIBC 2.38+ but Ubuntu 22.04 (the base VM) ships GLIBC 2.35. The only viable approach is building from source.

### Compiler: Must Use clang
The PEBL Makefile hardcodes `CC=clang CXX=clang++`. Make sure to `apt-get install clang`.

### Three Source Patches Required for Ubuntu 22.04

1. **PlatformFont.h — Missing `GetTTFFont()` accessor**
   - `PlatformTextBox.cpp` calls `renderFont->GetTTFFont()` but the method doesn't exist in `PlatformFont.h`
   - Fix: Add `TTF_Font * GetTTFFont() const { return mTTF_Font; }` to the class

2. **PlatformFont.cpp — SDL_ttf 2.20+ API guards**
   - PEBL uses `TTF_SetFontScriptName`, `TTF_DIRECTION_RTL`, `TTF_DIRECTION_LTR` which are only in SDL2_ttf >= 2.20
   - Ubuntu 22.04 ships SDL2_ttf 2.0.18
   - Fix: Wrap these calls in `#if SDL_TTF_COMPILEDVERSION >= SDL_VERSIONNUM(2,20,0)` guards

3. **PTextBox.cpp — Missing FORMATTED property**
   - `PlatformTextBox.cpp` calls `GetProperty("FORMATTED")` but `PTextBox.cpp` never initializes it
   - Only `PLabel.cpp` initializes it
   - Fix: Add `InitializeProperty("FORMATTED",Variant(0));` to PTextBox constructor

### Build Dependencies
```
build-essential g++ clang make flex bison git wget
libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev libsdl2-net-dev
libsdl2-gfx-dev libsdl2-mixer-dev libcurl4-openssl-dev libpng-dev
```

## Runtime Quirks

### Software Rendering is Mandatory
PEBL uses SDL2 for rendering. In QEMU/VNC environments, hardware OpenGL causes silent crashes. The `run-pebl` wrapper script must set:
```bash
export SDL_RENDER_DRIVER=software
```

### Battery Directory Must Be Writable
PEBL experiments write data output to subdirectories under the battery. Using symlinks (`ln -sf`) to a root-owned source directory fails. Must use `cp -r` to copy the battery to a user-writable location.

### Subject Code Conflict Dialog
Running an experiment twice with the same subject code (e.g., `-s 101`) triggers a dialog asking whether to overwrite. The `setup_task.sh` must clean up old data:
```bash
rm -rf /home/ga/pebl/battery/flanker/data/flanker-101* 2>/dev/null
```

## GUI Launch Quirks

### DBUS Session Required for gnome-terminal
When launching gnome-terminal via `su - ga -c "..."` (as hooks run as root), gnome-terminal needs the DBUS session bus. Without it:
```
Error constructing proxy for org.gnome.Terminal: Failed to execute child process "dbus-launch" (No such file or directory)
```

**Fix**: Install `dbus-x11` package and extract the DBUS address from the running gnome-session:
```bash
GA_PID=$(pgrep -u ga -f gnome-session | head -1)
DBUS_ADDR=$(grep -z DBUS_SESSION_BUS_ADDRESS /proc/$GA_PID/environ 2>/dev/null | tr '\0' '\n' | head -1)
su - ga -c "${DBUS_ADDR:+$DBUS_ADDR }DISPLAY=:1 setsid gnome-terminal ..."
```

### setsid + Environment Variables
`setsid DISPLAY=:1 command` does NOT work — `setsid` tries to execute `DISPLAY=:1` as a command.
Must use: `DISPLAY=:1 setsid command` (let the shell process the env var assignment).

### LibreOffice First-Run Dialogs
LibreOffice shows "Tip of the Day" and "What's New" dialogs on first launch. Suppress with:
```bash
LO_CONFIG="/home/ga/.config/libreoffice/4/user/registrymodifications.xcu"
mkdir -p "$(dirname "$LO_CONFIG")"
cat > "$LO_CONFIG" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" ...>
<item oor:path="/org.openoffice.Office.Common/Misc">
  <prop oor:name="ShowTipOfTheDay" oor:op="fuse"><value>false</value></prop>
</item>
</oor:items>
EOF
```

## Flanker Experiment Details
- Response keys: LEFT-SHIFT and RIGHT-SHIFT (NOT arrow keys)
- Stimuli: Arrow characters (<<<< and >>>>)
- Conditions: congruent, incongruent, neutral
- Default: 5 blocks, ~32 trials per block

## Stroop Color Experiment Parameters
- File: `battery/stroop-color/color-stroop.pbl`
- `custompractrials` (line 36): default value 8
- `customtrials` (line 37): default value 28
- Both used when `usepreset=0`

## Timing Notes
- Pre-start hook (build from source): ~150 seconds
- Post-start hook (setup): ~2 seconds
- Task-specific hooks: 1-2 seconds
- Total environment startup: ~155 seconds
