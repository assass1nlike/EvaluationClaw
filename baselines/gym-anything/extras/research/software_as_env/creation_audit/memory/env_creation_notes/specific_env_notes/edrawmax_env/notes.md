> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Wondershare EdrawMax Environment Notes

## Installation
- Package: `edrawmax_15.0.6_amd64.deb` (518MB)
- Download: Official EdrawMax Linux installer from Wondershare CDN
- Install: `dpkg -i edrawmax_*.deb` (requires dependencies: `libc6 libgl1 libglib2.0-0 etc.`)
- Install path: `/opt/apps/edrawmax/`
- Symlinks: `/usr/local/bin/edrawmax` → `/opt/apps/edrawmax/EdrawMax` (or wrapper script)
- Version confirmed: `dpkg -l edrawmax` → `15.0.6 amd64`

## Process & Launch
- Binary: `/usr/local/bin/edrawmax` or `/opt/apps/edrawmax/EdrawMax`
- Process name: `EdrawMax` (pgrep: `pgrep -f "EdrawMax"`)
- Launch with file: `su - ga -c "DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority edrawmax /path/file.eddx &"`
- Startup time: ~15-20 seconds after process appears
- Config dir: `~/Edraw/edrawmax/` (NOT `~/.edraw/edrawmax/`)
- Log file: `/tmp/edrawmax.log`

## Startup Dialogs (CRITICAL)
Two dialogs appear on every launch:

### Account Login Dialog
- EdrawMax prompts users to log in on every launch
- X button to dismiss at VG(863,197) = **actual(1294,296)** in 1920x1080
- Dialog position may vary between launches if triggered by gated features
  (use `wmctrl -lGx` to find actual position, then calculate X button)
- `task_utils.sh::dismiss_edrawmax_dialogs()` handles both dialogs

### File Recovery Dialog
- Appears if previous EdrawMax session was killed (not closed gracefully)
- X button to dismiss at VG(863,218) = **actual(1294,327)**
- Detected with `wmctrl -l | grep -q "File Recovery"` before clicking

## EdrawMax File Format (.eddx)
- ZIP archive containing: `document.xml`, `pages/page1.xml`, `rels/_rels.xml`,
  `rels/page1_rels.xml`, `theme.xml`, `templates.xml`, `thumbnail.jpeg`
- Template file: `/opt/apps/edrawmax/config/aiexample/flowchart_en.eddx` (8199 bytes)
- Bundled in `data/flowchart_en.eddx` for reliable access across all tasks

## Trial Restrictions (IMPORTANT)
- **File > Export**: ALL formats (PDF, PNG, JPEG, Word, PPT, etc.) are BLOCKED behind paywall
  - Dialog shows "Buy Now to Export" — no free export available
- **File > Print button**: Does NOT respond to automation (VNC click, xdotool, keyboard)
  - Likely a Chromium-embedded UI element that ignores synthetic input
- **Design > Solid Background**: Triggers Account Login dialog — gated in free tier
- **Most premium features** (connectors, export, sharing) require subscription

## Free Features (Verified Working)
- Creating new diagrams (flowchart, org chart, mind map, etc.) from New menu
- Adding/editing shapes from the Symbols panel
- Adding pages via right-click on page tab or Insert menu
- **Color themes** (Design > Color dropdown): 12 free themes available
  - Themes: Trendy, Fashionable, Dreamy, Delicate, Soft, Gentle, Mild, Peaceful, Warm
  - Applying a theme stores `<ThemeColor Name="...">` in `theme.xml` — VERIFIABLE
  - After applying, save via Ctrl+Shift+S → Save As dialog appears
- Save As (Ctrl+Shift+S) → saves as .eddx in current directory

## Task Design Notes

### create_flowchart
- Start state: EdrawMax home screen (no file open)
- Agent should: New > Flowchart > create diagram > save as git_pr_flowchart.eddx
- Verifier: checks file exists, is valid ZIP, has page content

### create_org_chart
- Start state: EdrawMax home screen (no file open)
- Agent should: New > Org Chart > create hierarchy → save as apache_org_chart.eddx
- Verifier: checks file exists, is valid ZIP, contains org chart structure

### create_mind_map
- Start state: EdrawMax home screen (no file open)
- Agent should: New > Mind Map > create topic map → save as linux_kernel_mindmap.eddx
- Verifier: checks file exists, is valid ZIP, contains mind map structure

### add_page_to_diagram
- Start state: `multipage_diagram.eddx` (flowchart) open in EdrawMax
- Agent should: Right-click page tab → Insert Page → name it "Notes" → add text box → save
- Verifier: checks for "Notes" page content in saved eddx OR file larger than original

### apply_theme
- Start state: `flowchart_task.eddx` (flowchart) open in EdrawMax
- Agent should: Design tab → Color dropdown → select "Warm" theme → Ctrl+Shift+S → save as themed_flowchart.eddx
- Verifier: checks themed_flowchart.eddx exists, is valid ZIP, contains ThemeColor/Warm in XML
- CONFIRMED: Warm theme stores `<ThemeColor Name="Warm" ID="126">` in theme.xml

## Automation Notes
- `task_utils.sh::take_screenshot()` uses `import -window root` (ImageMagick) — works with GNOME compositor
- `maximize_edrawmax()` uses `wmctrl -r "EdrawMax" -b add,maximized_vert,maximized_horz`
- `wait_for_edrawmax()` waits 15 extra seconds after process appears (UI not immediately ready)
- Account Login dialog dismiss is CRITICAL — must happen before agent begins task
- Sometimes dialog appears for blocked features mid-task; agent should dismiss with X button

## VNC Coordinate Notes (1920x1080)
- VG tool returns 1280x720 coords; actual = VG × 1.5
- Design tab: VG(392,78) → actual(588,117)
- Color dropdown (in Design toolbar): VG(500,103) → actual(750,155)
- Warm theme in Color panel: VG(808,383) → actual(1212,575)
- Save button in Save As dialog: VG(839,482) → actual(1259,723)
- Filename field in Save As: VG(663,482) → actual(995,723)
