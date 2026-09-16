> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Sugar Learning Platform Environment Notes

## Overview
Sugar (Sugar Labs) is an educational desktop environment originally created for the OLPC project. It uses a unique activity-based UI with an "activity ring" home view centered around an XO icon. Activities (apps) include Write (AbiWord), Browse, Calculate, TurtleArt, Chat, Pippy, Memorize, etc.

## Installation Quirks

### Package Names
Sugar activity packages use hyphens, not dots or underscores:
- Correct: `sugar-write-activity`, `sugar-browse-activity`, `sugar-calculate-activity`
- Wrong: `sugar-activity-write`, `sugar.write.activity`

The `sucrose` metapackage pulls in the Sugar shell and core activities. Install it first, then add specific activity packages.

### TurtleArt Not in Ubuntu Packages
TurtleArt (`org.laptop.TurtleArtActivity`) is NOT available as an Ubuntu package. It must be installed from the Sugar Labs GitHub repository by downloading the zip and extracting to `/usr/share/sugar/activities/TurtleArt.activity/`. The GitHub URL is: `https://github.com/sugarlabs/turtleart-activity/archive/refs/heads/master.zip`

### GSettings Schema Bug (Ubuntu 22.04)
The Sugar3 Python library (`profile.py`) references a `favorites-layout` key in the `org.sugarlabs.desktop` GSettings schema, but this key is missing from the Ubuntu 22.04 package. This causes a fatal `GLib-GIO-ERROR` crash when Sugar starts.

**Fix**: Patch the schema XML file at `/usr/share/glib-2.0/schemas/org.sugarlabs.gschema.xml` to add the missing key before the `launcher-interval` key, then run `glib-compile-schemas`:

```python
# Insert before <key name="launcher-interval"
new_key = '''        <key name="favorites-layout" type="s">
            <default>'ring-layout'</default>
            <summary>Favorites Layout</summary>
            <description>Layout of favorite activities on the home view.</description>
        </key>
'''
```

### dbus-x11 Required
Sugar requires `dbus-launch` which is provided by the `dbus-x11` package. Without it, Sugar fails to start with "dbus-launch: command not found".

### First-Run Intro Screen
Sugar normally shows a first-run wizard asking for a nickname and color. Setting the `SUGAR_PROFILE_NAME` environment variable (in `/etc/environment`) causes Sugar to auto-create the profile with that name, skipping the intro screen entirely.

```bash
echo 'SUGAR_PROFILE_NAME=Learner' >> /etc/environment
```

This triggers `create_profile_with_nickname()` in Sugar's `main.py`, which is much more reliable than trying to set gsettings values before Sugar starts.

## Session Configuration

### Sugar Must Run as GDM Session
Sugar does NOT work well when run inside Xephyr or alongside GNOME. It must be the actual desktop session managed by GDM.

**Configuration steps:**
1. Set GDM default session: `sed -i 's/DefaultSession=ubuntu-xorg.desktop/DefaultSession=sugar.desktop/' /etc/gdm3/custom.conf`
2. Set AccountsService session:
```
/var/lib/AccountsService/users/ga:
[User]
Language=
XSession=sugar
SystemAccount=false
```
3. Restart accounts-daemon and GDM in the post_start hook

### Xephyr Does NOT Work
Attempted running Sugar in Xephyr on :2 alongside GNOME on :1. Problems:
- xdotool clicks don't register on Sugar GTK widgets in Xephyr
- Even when clicks register, GNOME on :1 intercepts mouse events
- Sugar's activity icons don't respond to xdotool click events (likely GTK event handling specific to Sugar's canvas)

### XAUTHORITY Location
The real X authority file for the GDM session is at `/run/user/1000/gdm/Xauthority`, NOT at `~/.Xauthority` (which is 0 bytes).

## Launching Activities

### sugar-launch Command
Activities can be launched programmatically using `sugar-launch <bundle_id>`:
- Write: `sugar-launch org.laptop.AbiWordActivity`
- TurtleArt: `sugar-launch org.laptop.TurtleArtActivity`
- Browse: `sugar-launch org.laptop.WebActivity`
- Calculate: `sugar-launch org.laptop.Calculate`

### DBUS Session Bus Required
`sugar-launch` communicates with the Sugar Shell via DBUS (`org.laptop.Shell`). When running from hook scripts (which execute as root), the user's DBUS session bus must be explicitly set:

```bash
SUGAR_ENV="DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"
su - ga -c "$SUGAR_ENV sugar-launch org.laptop.AbiWordActivity"
```

Without `DBUS_SESSION_BUS_ADDRESS`, sugar-launch fails with: `org.freedesktop.DBus.Error.NameHasNoOwner: Could not get owner of name 'org.laptop.Shell'`

### Harmless DBUS Errors
When launching activities via `sugar-launch`, you'll see DBUS errors like `ValueError: Failed to convert metadata value to bytes` from the datastore. These are harmless - the activity still launches and functions correctly. The error comes from Sugar's datastore trying to read metadata for the new Journal entry, but the metadata format has a minor incompatibility on Ubuntu 22.04.

Similarly, `WARNING: Failed to connect to the session manager: SESSION_MANAGER environment variable not defined` is harmless - it just means the activity isn't connected to a GNOME session manager, which is expected since Sugar has its own session management.

### xdotool Limitations with GTK Canvas Widgets
xdotool synthetic X11 events do NOT work with Sugar's custom GTK canvas widgets:
- **Home view activity icons**: Clicks don't trigger activities. Use `sugar-launch` instead.
- **TurtleBlocks block palette**: Drag operations don't work with xdotool.
- **Sugar menus and text fields**: These DO respond to xdotool (standard GTK widgets).

**Why real agents work**: The gym_anything `env.step()` API injects actual X11 events (ButtonPress/ButtonRelease/MotionNotify) into the X server via XTest or equivalent, not xdotool's XSendEvent synthetic events. GTK widgets that ignore synthetic events (like Sugar's canvas) still process real injected events normally. This is the same distinction that makes VNC-based interaction work where xdotool fails.

Always use `sugar-launch` to open activities programmatically in setup scripts. For task interaction, rely on real agent mouse events via `env.step()`.

## Timing

### Boot Sequence
1. Pre-start hook (install): ~90-100s (apt-get install, schema patching, data download)
2. Post-start hook (setup): ~20s (restart GDM + wait for jarabe.main)
3. Pre-task hook: ~5-13s depending on activity launch

### Wait for Sugar
After restarting GDM, wait for the `jarabe.main` Python process to appear (polling with `pgrep -f "jarabe.main"`). Then add 5s extra for the home view to fully render.

## Real Data

### Alice in Wonderland
Downloaded from Project Gutenberg (`https://www.gutenberg.org/cache/epub/11/pg11.txt`). A local excerpt is provided as fallback in `data/alice_in_wonderland_excerpt.txt`.

### TurtleArt Programs
Two real TurtleArt `.ta` program files:
- `spiral.ta` - Draws a geometric spiral using repeat/forward/right
- `flower.ta` - Draws a flower pattern using nested loops and color

The `.ta` format is JSON arrays where each element represents a block with `[id, type, x, y, connections]`.

### Sugar Journal Import (Unreliable)
Manual creation of Journal datastore entries at `/home/ga/.sugar/default/datastore/store/<uid>/` causes `ValueError: Failed to convert metadata value to bytes` from the carquinyol metadata reader. The Sugar datastore has strict binary encoding requirements for metadata that are hard to replicate manually. Prefer placing files on the filesystem instead (e.g., `/home/ga/Documents/`) and letting the agent load them through the activity UI.

### Write Activity Title Field
The document title in Write is NOT visible in the default toolbar view. To access it, click the Activity tab (yellow pencil icon, first icon in top toolbar). This expands a secondary row showing the title text field (default: "Write Activity") and export buttons (RTF, HTML, TXT).

## Environment Specifications

| Setting | Value |
|---------|-------|
| Base image | `ubuntu-gnome-systemd_highres` |
| CPU | 4 |
| RAM | 4GB |
| Resolution | 1920x1080 |
| Network | Required (for data download) |
| Runtime | `sysbox-runc` (systemd support) |
| Privileged | true |
