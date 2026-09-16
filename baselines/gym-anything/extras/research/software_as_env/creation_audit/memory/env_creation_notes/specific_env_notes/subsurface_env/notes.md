> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Subsurface Dive Log Environment Notes

## App Overview
- **Application**: Subsurface — open-source dive log by Linus Torvalds / Dirk Hohndel
- **Type**: Desktop GUI application (Qt-based)
- **Homepage**: https://subsurface-divelog.org/
- **GitHub**: https://github.com/subsurface/subsurface

## Installation

### Method: Stable PPA (recommended)
```bash
add-apt-repository -y ppa:subsurface/subsurface
apt-get update
apt-get install -y subsurface
```
- PPA on Ubuntu 22.04 (Jammy): works reliably, installs latest stable version
- Fingerprint: `33019F96E07BA4CBE58E41BBCDF92DBFB511CE42`

### AppImage fallback URL
```
https://subsurface-divelog.org/downloads/Subsurface-6.0.5504-CICD-release.AppImage
```

## Data Format

- **Native format**: `.ssrf` (XML-based, root element: `<divelog program='subsurface' version='2'>`)
- **Structure**: `<settings>` → `<dives>` → `<trip>` → `<dive>`
- Dive attributes: `number`, `date`, `time`, `duration`, `tags`, `rating`, `visibility`
- Child elements: `<location>` (with optional `gps="lat lon"` attribute), `<notes>`, `<buddy>`, `<divemaster>`, `<suit>`, `<cylinder>`, `<divecomputer>`, `<sample>`
- Sample format for cylinder: `<cylinder size="12.0l" workpressure="200.0bar" description="Al80" o2="32.0%" start="200.0bar" end="100.0bar"/>`

## Real Sample Data

- **Source**: `SampleDivesV2.ssrf` from official Subsurface GitHub repository
- **URL**: `https://raw.githubusercontent.com/subsurface/subsurface/master/dives/SampleDivesV2.ssrf`
- **Size**: 1,653,205 bytes (~1.65 MB)
- **Content**: 29 real dives from actual dive computers across:
  - Hoodsport, WA, USA (Sund Rock: Dec 2010; Yellow House: Sep 2011, Sep 2014)
  - Larnaca, Cyprus (Zenobia wreck: Oct 2011) — 6 dives, rating 3-5 stars
  - Koror, Palau (Blue Corner, Blue Hole, etc.: Jun 2013) — 11 dives, GPS coords
  - Bonaire (Divi Flamingo House Reef: Oct 2014) — 1 dive, 119 min, GPS coords
- **Dive computers**: Aeris A300CS, Heinrichs Weikamp OSTC 3, Shearwater Petrel, Uemis Zurich
- **Dive numbers**: 2-5, 85-90, 91-96, 223-233, 333, 348 (actual career dive numbers of a real diver)
- Dive #2 buddy is "David", diveguide is "Jeff", notes: "First OWD dive unbelievably cold"
- Dive #85 already has tag `shore`; adding tags "deep" and "deco" works fine

## Configuration File

Subsurface stores config in `~/.config/Subsurface/Subsurface.conf` (Qt INI format).

**Critical: Include the `[UpdateManager]` section to prevent the update check dialog:**
```ini
[General]
CloudEnabled=false
AutoCloudStorage=false
CheckForUpdates=false
BackgroundCheck=false
DefaultFilename=/home/ga/Documents/dives.ssrf

[Units]
pressure=0
temperature=0
length=0
volume=0
weight=0
time=0
verticalspeedtime=0

[UpdateManager]
DontCheckForUpdates=true
NextCheck=2461107

[Recent_Files]
File_1=/home/ga/Documents/dives.ssrf
```

**Unit encoding** (for verification of `change_to_imperial` task):
- When user clicks "Imperial" radio button in Preferences > Units, Subsurface writes `unit_system=1` (NOT just `length=1`)
- Legacy encoding also present: `length=0` = meters, `length=1` = feet
- Best check: `unit_system=1` in `[Units]` section (set by clicking Imperial)
- Visual confirmation: depths in dive list show in feet (e.g., 35ft, 36ft)

## Dialog Suppression

### Problem 1: Update Check Dialog
- **Dialog title**: "Opening datafile from older version" / "Automatic check for updates"
- **Buttons**: "Accept" / "Decline"
- **Fix**: Add `[UpdateManager] DontCheckForUpdates=true` to Subsurface.conf BEFORE launch
- **Also**: Warm-up launch in post_start hook suppresses remaining dialogs via Escape key

### Problem 2: Information Tooltip
- Small tooltip overlaying the dive profile graph when a dive is selected
- **Dismiss**: Click the X close button or press Escape
- **Coordinates** (1280x720): X button at approximately (794, 80) → scale to actual resolution

## Launch Pattern

```bash
# From task setup scripts:
pkill -9 -f subsurface 2>/dev/null || true
sleep 2
cp /opt/subsurface_data/SampleDivesV2.ssrf /home/ga/Documents/dives.ssrf
su - ga -c "DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority \
    setsid subsurface /home/ga/Documents/dives.ssrf \
    >/home/ga/subsurface_task.log 2>&1 &"
```

**Key flags**:
- Must use `setsid` when launching from SSH hooks (cross-cutting pattern)
- Must set `XAUTHORITY=/run/user/1000/gdm/Xauthority` explicitly
- Always pass the file path as argument to open the logbook on launch

## UI Layout (1920x1080)

```
┌─────────────────────────────────────────────────────────────┐
│ Menu: File  Edit  Import  Log  View  Help                    │
│ Tabs: Notes | Equipment | Information | Summary | Media ...  │
├──────────────────────────┬──────────────────────────────────┤
│    Dive Details Panel    │         Dive Profile Graph        │
│  (date, time, location,  │  (depth-over-time, temperature,   │
│   buddy, notes, tags)    │   tank pressure, events)         │
│                          │                                   │
├──────────────────────────┴──────────────────────────────────┤
│ Dive List (lower half)     │  Map (lower right)             │
│  #, Date, Rating, Depth,   │  (GPS location for dive site)  │
│  Duration, Media, Buddy    │                                 │
└────────────────────────────┴────────────────────────────────┘
```

## Dive List Coordinates (1280x720 scale, multiply by 1920/1280 and 1080/720)

From testing with the sample data (dive list sorted newest first):
- Sep 2011 dives (#85, #86) visible at y ≈ 476-503
- Dec 2010 dives (#2-5) visible at y ≈ 515-554
- Dive #2 is at approximately y=554 (→ y=831 in 1920x1080)
- x center of dive list ≈ 400 (→ x=600 in 1920x1080)

Note: The dive list is long (29 dives) so scrolling may be needed. The Dec 2010 dives are near the bottom of the list.

## Qt Runtime Warnings (Expected)

These appear in task logs but are **harmless**:
```
QStandardPaths: XDG_RUNTIME_DIR not set, defaulting to '/tmp/runtime-ga'
QObject::connect(QQuickWindow, QDeclarativeGeoMap_QML_6): invalid nullptr parameter
```

## 10 Tasks

| Task | Dive Target | Description |
|------|-------------|-------------|
| `add_new_dive` | New dive | Add dive: Jul 15 2023, Blue Hole Dahab, 45min, 25m, buddy Ahmed Hassan |
| `edit_dive_buddy` | Dive #2 | Change buddy from "David" to "Michael Chen" |
| `add_nitrox_cylinder` | Dive #3 | Add 12L/200bar EAN32 cylinder |
| `create_dive_trip` | New trip + dive | "Red Sea Liveaboard 2022", Hurghada Egypt |
| `add_dive_tags` | Dive #85 | Add tags "deep" and "deco" (already has tag "shore") |
| `export_dives_csv` | All dives | Export to /home/ga/Documents/dive_log.csv |
| `update_dive_notes` | Dive #4 | Add notes about Pacific octopus sighting |
| `change_to_imperial` | Preferences | Switch units from metric to imperial |
| `set_dive_site_gps` | Dive #2 | Add GPS 47.4005 -123.1420 (Sund Rock, no GPS in data) |
| `plan_basic_dive` | Planner | Plan 30m/40min air dive, save to logbook |

## Interactively Verified Workflows (2026-02-21)

### edit_dive_buddy (verified ✅)
1. Click "Hoodsport, WA, USA, Dec 2010 (4 dives)" trip header to expand
2. Click Dive #2 (Sat Dec 4, 2010) row
3. Triple-click buddy field in detail panel (middle left panel)
4. Type "Michael Chen" → Ctrl+S
5. Verified: SSRF `<dive number='2' ... buddy='Michael Chen' ...>`

### change_to_imperial (verified ✅)
1. File menu (top-left) → Preferences
2. Click "Units" in left sidebar of preferences dialog
3. Click "Imperial" radio button → all units change
4. Click Save button
5. Verified: `/home/ga/.config/Subsurface/Subsurface.conf` shows `unit_system=1`

### export_dives_csv (verified ✅)
1. File → Export (or Ctrl+E)
2. Select "CSV dive list" in left list; select "All dives" on right
3. Click OK
4. In file dialog: navigate to Documents folder (double-click)
5. Click in filename field, type "dive_log.csv", click Save
6. Verified: `/home/ga/Documents/dive_log.csv` created (10,254 bytes, 29 rows)

### add_dive_tags (verified ✅)
1. Click "Hoodsport, WA, USA, Sep 2011 (6 dives)" to expand
2. Click Dive #85 (Thu Sep 29, 2011 — last/bottom item in the group)
3. In Tags field (Notes tab, under buddy): triple-click to select all
4. Type "deep, deco, shore" (include existing shore tag + new ones)
5. Ctrl+S → verified: SSRF `tags='shore, deep, deco'`
Note: Tags show as colored chip labels. Triple-click selects all chips for replacement.

## GPS Location Storage in SSRF

GPS coordinates are stored in the `<divesites>` section (not directly in `<location>` child of dive):
```xml
<divesites>
  <site uuid='eea339da' name='Yellow House' gps='47.40008 -123.14225' .../>
</divesites>
```
And dives reference it via: `<dive ... divesiteid='eea339da' ...>`

For Dive #2 (Sund Rock), no GPS coordinates exist in the original data — this is what the `set_dive_site_gps` task asks the agent to add.

## Verification Notes (External VLM)

For programmatic verification of `.ssrf` files:
```python
import xml.etree.ElementTree as ET
tree = ET.parse('/home/ga/Documents/dives.ssrf')
root = tree.getroot()
dives = root.findall('.//dive')
target_dive = next((d for d in dives if d.get('number') == '2'), None)
# Check buddy
buddy = target_dive.get('buddy', '')
# Check tags
tags = target_dive.get('tags', '')
# Check notes
notes_elem = target_dive.find('notes')
notes = notes_elem.text if notes_elem is not None else ''
# Check cylinder
cylinders = target_dive.findall('cylinder')
# Check GPS
loc_elem = target_dive.find('location')
gps = loc_elem.get('gps', '') if loc_elem is not None else ''
```

For `change_to_imperial`, check (use `unit_system=1` which is what Subsurface writes):
```python
# Read as plain text — configparser may struggle with Qt INI format
with open('/home/ga/.config/Subsurface/Subsurface.conf') as f:
    conf = f.read()
assert 'unit_system=1' in conf  # Imperial mode
```

For GPS in dive site (set_dive_site_gps task):
```python
# GPS stored in divesites section, not in dive element
divesites = root.find('divesites')
for site in divesites.findall('site'):
    if site.get('uuid') == dive2.get('divesiteid'):
        gps = site.get('gps', '')  # 'lat lon' space-separated
```
