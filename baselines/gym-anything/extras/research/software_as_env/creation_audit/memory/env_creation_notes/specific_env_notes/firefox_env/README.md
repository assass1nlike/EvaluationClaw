> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Firefox Environment Creation Notes

## Overview

This document captures learnings from creating the Firefox browser environment (`firefox_env`).

## Key Challenges and Solutions

### 1. Firefox Profile Location (Snap vs Regular)

**Challenge**: On Ubuntu, Firefox is installed via Snap by default, which uses a different profile location than traditional Firefox installations.

**Solution**: The export script dynamically detects the profile location:
```bash
# Check both locations
SNAP_PROFILE_DIR="/home/ga/snap/firefox/common/.mozilla/firefox/default.profile"
REGULAR_PROFILE_DIR="/home/ga/.mozilla/firefox/default.profile"

if [ -f "$SNAP_PROFILE_DIR/places.sqlite" ]; then
    PROFILE_DIR="$SNAP_PROFILE_DIR"
elif [ -f "$REGULAR_PROFILE_DIR/places.sqlite" ]; then
    PROFILE_DIR="$REGULAR_PROFILE_DIR"
else
    # Dynamic fallback
    FOUND_DB=$(find /home/ga -name "places.sqlite" 2>/dev/null | head -1)
    PROFILE_DIR=$(dirname "$FOUND_DB")
fi
```

### 2. Database Flushing

**Challenge**: Firefox doesn't immediately write bookmarks to `places.sqlite`. During testing, bookmarks appeared in the UI but not in the database.

**Solution**: Close Firefox before querying the database:
```bash
pkill -u ga firefox 2>/dev/null
sleep 3
# Now database is flushed
sqlite3 "$PLACES_DB" "SELECT ..."
```

### 3. SQLite Database Locking

**Challenge**: When Firefox is running, `places.sqlite` is locked and queries may fail.

**Solution**: Copy the database before querying:
```bash
cp "$PLACES_DB" /tmp/places_copy.sqlite
sqlite3 /tmp/places_copy.sqlite "SELECT ..."
rm /tmp/places_copy.sqlite
```

### 4. Coordinate Scaling for VLM

**Challenge**: `ask_cua.py` returns coordinates at 1280x720 resolution, but the environment runs at 1920x1080.

**Solution**: Scale coordinates proportionally:
```python
# VLM returns coordinates at 1280x720
vlm_x, vlm_y = 867, 400  # Example VLM coordinates

# Scale to actual resolution (1920x1080)
actual_x = int(vlm_x * 1920 / 1280)  # 1300
actual_y = int(vlm_y * 1080 / 720)   # 600
```

### 5. First-Run Dialogs

**Challenge**: Firefox shows various first-run dialogs, data collection prompts, and update notifications.

**Solution**: Configure `user.js` preferences to disable all first-run experiences:
```javascript
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutConfig.showWarning", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
// ... many more
```

## Firefox Profile Structure

```
default.profile/
├── places.sqlite      # Bookmarks and history
├── prefs.js           # User preferences (auto-generated)
├── user.js            # Custom preferences (our config)
├── cookies.sqlite     # Cookies database
├── formhistory.sqlite # Form autofill data
└── key4.db            # Encryption keys
```

## Important Firefox Databases

### places.sqlite

Contains bookmarks and browsing history:
- `moz_places`: URLs visited
- `moz_bookmarks`: Bookmark entries (link to moz_places via `fk` column)
- `moz_historyvisits`: Visit history

Bookmark query:
```sql
SELECT b.id, b.title, p.url
FROM moz_bookmarks b
JOIN moz_places p ON b.fk = p.id
WHERE b.type = 1;  -- type 1 = bookmark, type 2 = folder
```

## Testing Commands

### Take Screenshot
```bash
DISPLAY=:1 import -window root /tmp/screenshot.png
# OR
DISPLAY=:1 scrot /tmp/screenshot.png
```

### Navigate via xdotool
```bash
DISPLAY=:1 xdotool key ctrl+l                      # Focus address bar
DISPLAY=:1 xdotool type "https://www.example.com"  # Type URL
DISPLAY=:1 xdotool key Return                       # Navigate
```

### Add Bookmark
```bash
DISPLAY=:1 xdotool key ctrl+d                       # Open bookmark dialog
DISPLAY=:1 xdotool key Return                       # Save (if button focused)
# OR click Save button coordinates
DISPLAY=:1 xdotool mousemove X Y click 1
```

### Query Bookmarks
```bash
sqlite3 /path/to/places.sqlite "
SELECT p.url, b.title
FROM moz_bookmarks b
JOIN moz_places p ON b.fk = p.id
WHERE b.type = 1;"
```

## Environment Registration

Add to `constants.py`:
```python
# Firefox browser environment
try:
    firefox_tasks = [x for x in os.listdir('benchmarks/cua_world/environments/firefox_env/tasks') if x.find('.')==-1]
except FileNotFoundError:
    firefox_tasks = ['add_bookmark']

# In ENV_TASK_SPLITS:
'firefox_env': {
    'all' : firefox_tasks,
    'train' : firefox_tasks,
    'test' : [],
},
```

## Task Ideas for Firefox

1. **add_bookmark** (implemented) - Add a website as a bookmark
2. **download_file** - Download a file from a URL
3. **fill_form** - Complete a web form
4. **manage_tabs** - Open/close/switch between tabs
5. **change_settings** - Modify Firefox preferences
6. **import_bookmarks** - Import bookmarks from file
7. **clear_history** - Clear browsing history
8. **install_extension** - Install a Firefox extension

## Potential Issues

1. **Network Availability**: Tasks requiring internet need `"net": true` in env.json
2. **Resolution Changes**: VLM coordinate scaling must match actual resolution
3. **Timing Issues**: Web pages take time to load; use appropriate waits
4. **Database State**: Fresh environment may not have places.sqlite until Firefox runs
5. **Profile Corruption**: If Firefox crashes, profile may need recovery

## Verification Patterns

For browser tasks, prefer database verification over screenshot/UI verification:
- More reliable (not dependent on visual changes)
- Faster (no need to wait for UI updates)
- Clearer pass/fail criteria

Example verification flow:
1. Close browser to flush database
2. Copy database to avoid lock issues
3. Query database for expected state
4. Compare against task requirements
