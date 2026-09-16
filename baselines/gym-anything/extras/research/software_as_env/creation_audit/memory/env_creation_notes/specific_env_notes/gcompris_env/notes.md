> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# GCompris Environment — Specific Notes

**Created**: 2026-02-18
**GCompris version**: 2.3 (Ubuntu 22.04 `gcompris-qt` package)
**Task count**: 5
**Base image**: `ubuntu-gnome-systemd_highres` (QEMU, 1920×1080)

---

## Installation

Package: `apt-get install -y gcompris-qt gcompris-qt-data`

**CRITICAL**: The binary installs to `/usr/games/gcompris-qt`, NOT to a standard PATH location.
- Check for it at `/usr/games/gcompris-qt` explicitly
- `command -v gcompris-qt` will fail unless you add a symlink
- Fix in install script: `ln -sf /usr/games/gcompris-qt /usr/local/bin/gcompris-qt`

All scripts use this detection pattern:
```bash
get_gcompris_bin() {
    if [ -x "/usr/games/gcompris-qt" ]; then
        echo "/usr/games/gcompris-qt"
    elif command -v gcompris-qt &>/dev/null; then
        echo "gcompris-qt"
    elif command -v gcompris &>/dev/null; then
        echo "gcompris"
    else
        echo "ERROR: GCompris binary not found" >&2; exit 1
    fi
}
```

---

## No `--launch` Flag in GCompris 2.3

GCompris 3.0+ supports `--launch <activity-name>` to open a specific activity directly.
**GCompris 2.3 does NOT support `--launch`** — it ignores the flag or errors.

All task setup scripts navigate to the correct category via xdotool mouse clicks after GCompris starts.

---

## Launch Pattern (sudo -u ga with XAUTHORITY)

The scripts run as root (hook execution context). To launch GUI apps:
```bash
sudo -u ga DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority /usr/games/gcompris-qt -m &
```

**Why `sudo -u ga` and not `su - ga -c`?**
- `su - ga -c` can fail or hang when called from a non-interactive SSH session
- `sudo -u ga` with explicit XAUTHORITY is more reliable in all contexts

**Audio mute**: Always launch with `-m` flag. GCompris shows PulseAudio errors in a VM without sound:
```
PulseAudioService: pa_context_connect() failed
```
These are non-fatal. The `-m` flag suppresses the audio subsystem attempt.

---

## First-Run Dialog Suppression

Write config before launching to suppress first-run dialogs:

**`/home/ga/.config/gcompris-qt/gcompris-qt.conf`**:
```ini
[General]
fullscreen=false
isFirstRun=false
enableAudio=false
showLockAtStart=false
filterLevelMin=1
filterLevelMax=6
```

The warm-up launch in `post_start` (setup_gcompris.sh) also settles any remaining first-run state.

---

## Window Detection and Maximization

```bash
# Wait for GCompris window to appear (up to 40s)
while [ $elapsed -lt 40 ]; do
    if DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority wmctrl -l | grep -qi "gcompris"; then
        echo "GCompris window ready"; break
    fi
    sleep 2; elapsed=$((elapsed + 2))
done

# Maximize
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz
```

After maximization, sleep 2s before clicking — GCompris needs time to re-render at the new size.

---

## Category Navigation (1920×1080)

GCompris has a category icon strip at the top of the main menu. Icons are at y≈97 (actual).

| Category | Icon | Actual Coords (1920×1080) |
|----------|------|---------------------------|
| Math/Arithmetic | sheep | (1057, 97) |
| Science/Logic | penguin | (487, 97) |
| Science/Experiment | pig | (682, 97) |
| Dino/Sports/Misc | dinosaur | (862, 97) |
| ABC/Reading | cow | (1447, 97) |
| Games | frog | (1627, 97) |

Navigate using xdotool:
```bash
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xdotool mousemove 862 97 click 1
sleep 3
```

**Important**: After clicking a category, wait 3s for activities to load before clicking a tile.

---

## Activity Tabs

Some categories have tabs (e.g., Math has Arithmetic, Algebra, Missing Letter; ABC has Letters, Words, Numbers).

- **Math > Arithmetic tab**: click at actual (660, 204) after entering Math/sheep category
- **ABC > Letters tab**: click at actual (660, 204) after entering ABC/cow category

The category sub-tab strip is at y≈204 (actual).

---

## Activity Locations (Verified)

| Activity | Category | Tab | Notes |
|----------|----------|-----|-------|
| **Learn additions** | Math (sheep) | Arithmetic | Small tiles in a grid; shows number sentences |
| **Maze** | Dino (dinosaur) | (default) | Penguin navigates brick maze; arrow keys |
| **Alphabet sequence** | ABC (cow) | Letters | Shows floating letter; press matching key |
| **Mixing paint colors** | Science/Exp (pig) | Experiment | Magenta/cyan/yellow tubes; match target color |
| **Memory game with images** | Dino (dinosaur) | (default) | 4-card grid; flip and match animal pairs |

---

## Activities NOT in GCompris 2.3

- **"Algebra"** — Does NOT exist. Use "Learn additions" instead.
- **"Click on a lowercase letter"** — Exists but is AUDIO-DEPENDENT (spoken letter, no visual target). Avoid for tasks requiring visual verification.
- **"--launch" flag** — Not supported; navigate via GUI clicks.

---

## Escape Key Behavior

Pressing Escape in GCompris EXITS the application (or returns to the home Favorites screen from a category). Do NOT use Escape to go back. Use the home (house) icon button in the bottom bar of GCompris instead.

---

## Screenshot Method

Use `import -window root` (ImageMagick) for screenshots — NOT `scrot`. In GNOME Compositor environments, `scrot` can return a blank/black image.

```bash
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority import -window root /tmp/screenshot.png
```

---

## Voice Data Download

On first run, GCompris downloads voice data:
```
Downloading resource file "data2/voices-ogg/voices-en_US.rcc"
```
This is ~10MB, downloads to `/home/ga/.cache/KDE/gcompris-qt/data2/voices-ogg/voices-en_US.rcc`. Subsequent runs show:
```
Local resource is up-to-date: "voices-en_US.rcc"
```
The warm-up launch in `post_start` triggers this download, so task pre_task hooks don't wait for it.

---

## Task Verifier Pattern

All 5 tasks use `"mode": "program"` verifiers (`verifier.py`). Since GCompris has no persistent state file or API, verification relies on visual inspection (VLM screenshot analysis) — the verifier takes a screenshot and passes it to the LLM judge.

Verifier skeleton:
```python
def verify_<task>(env) -> dict:
    # Take screenshot
    screenshot = env.screenshot()
    # Pass to judge with task-specific criteria
    result = env.judge(screenshot, criteria="...")
    return {"success": result["success"], "reason": result["reason"]}
```

---

## Task Files Structure

```
benchmarks/cua_world/environments/gcompris_env/
├── env.json
├── scripts/
│   ├── install_gcompris.sh    # pre_start: apt install gcompris-qt + symlink
│   ├── setup_gcompris.sh      # post_start: write config + warm-up launch
│   └── task_utils.sh          # shared: kill_gcompris, launch_gcompris, maximize_gcompris
├── tasks/
│   ├── navigate_activity/     # Find and click Learn additions in Math > Arithmetic
│   ├── complete_maze/         # Navigate to Dino category, complete Maze with arrow keys
│   ├── type_letters/          # Navigate to ABC > Letters, complete Alphabet sequence
│   ├── color_mix/             # Navigate to Science/Exp, match color in Mixing paint colors
│   └── memory_game/           # Navigate to Dino category, match 3+ pairs in Memory game
└── evidence_docs/
    ├── README.md
    ├── ev_t1_navigate.png
    ├── ev_t2_maze.png
    ├── ev_t3_letters.png
    ├── ev_t4_color.png
    └── ev_t5_memory.png
```
