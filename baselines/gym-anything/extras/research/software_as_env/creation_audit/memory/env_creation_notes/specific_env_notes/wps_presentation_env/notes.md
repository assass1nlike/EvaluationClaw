> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# WPS Presentation Environment — Creation Notes

## Installation

- **Package**: WPS Office 11.1.0.11723 DEB from CDN
  `https://wdl1.pcfg.cache.wpscdn.com/wpsdl/wpsoffice/download/linux/11723/wps-office_11.1.0.11723.XA_amd64.deb`
- **Binary**: `/opt/kingsoft/wps-office/office6/wpp` (symlink: `/usr/bin/wpp`)
- **Config dir**: `~/.config/Kingsoft/`
- **Process detection**: `pgrep -f "office6/wpp"`
- **Missing fonts**: Install from `https://github.com/iykrichie/wps-office-19-missing-fonts-on-Linux`

## Real Data

- **File**: `2411-Performance_Up.pptx` from Apache POI test corpus
- **URL**: `https://raw.githubusercontent.com/apache/poi/trunk/test-data/slideshow/2411-Performance_Up.pptx`
- **Content**: 48-slide Apache HTTP Server performance analysis presentation by Sander Temme
- **License**: Apache License 2.0
- **Size**: ~633KB; hard-fail in post_start if < 50KB

## First-Run Dialogs — CRITICAL

WPS shows two one-time dialogs that must be accepted during post_start warm-up:

### 1. EULA Dialog

- **Window title**: "Kingsoft Office Software License Agreement and Privacy Policy"
- **Appears**: On first WPS launch after installation
- **Side effect**: WPS opens Firefox to display EULA web page — this MUST be killed before clicking
- **Detection**: `xdotool search --name "Kingsoft Office"` returns a decimal WID
- **Dismissal** (verified working on 1920×1080):
  ```bash
  pkill -f firefox   # kill Firefox first
  sleep 2
  wmctrl -ia "$EULA_WID"   # raise dialog to front
  sleep 1
  xdotool mousemove 645 648 click 1   # click checkbox
  sleep 1
  xdotool mousemove 1290 648 click 1  # click "I Confirm"
  ```
- **What does NOT work**: `xdotool key --window WID Tab Tab space` (Qt ignores XSendEvent)
- **What DOES work**: `xdotool mousemove X Y click 1` (uses XTEST for mouse, accepted by Qt)

### 2. "WPS Office" File Format Check Dialog

- **Window title**: "WPS Office"
- **Appears**: On FIRST PPTX file open (not on bare `wpp` launch)
- **Fix**: Launch warm-up with the PPTX file: `wpp '/home/ga/.../performance.pptx'`
  so this dialog is triggered and dismissed during post_start
- **OK button**: ~(1280, 630) on 1920×1080

## wait_for_wps False Positive Bug

Matching on `"wps\|presentation\|kingsoft"` matches the EULA dialog title ("Kingsoft Office
Software License Agreement") causing false-positive: the function returned as soon as the
EULA appeared (10s), before the PPTX was loaded. The EULA blocked WPS from loading the file.

**Fix**: Match only on `"performance\.pptx"` — appears in window title only after file is loaded.

## task_utils.sh Key Functions

- `kill_wps()` — kills all WPS processes
- `reset_presentation()` — copies performance.pptx from `/opt/wps_samples/` to working dir
- `launch_wps_with_file(path)` — launches `su - ga -c "DISPLAY=:1 wpp '$path' &"`
- `dismiss_eula_if_present()` — checks for EULA, kills Firefox, raises+clicks to accept
- `wait_for_wps(timeout)` — calls dismiss_eula in loop, waits for "performance.pptx" in title
- `maximize_wps()` — `wmctrl -r ":ACTIVE:" -b add,maximized_vert,maximized_horz`

## 5 Tasks

| Task ID | Description | Setup | Start State |
|---------|-------------|-------|-------------|
| edit_title_slide | Edit title on slide 1 to "Apache Performance Benchmark Report" | Ctrl+Home | Slide 1 |
| add_new_slide | Add slide at end with title "Summary and Conclusions" | Ctrl+End | Slide 48 |
| insert_text_box | Insert text box on slide 2 with "Performance data collected 2024" | Page_Down | Slide 2 |
| apply_design_theme | Apply a design theme from Design tab | Ctrl+Home | Slide 1 |
| export_to_pdf | Export to /home/ga/Documents/presentations/performance.pdf (WPS default) | Ctrl+Home | Slide 1 |

All tasks use stub (VLM) verifiers — `{"passed": True, "score": 100}`.

## Timing

- env.reset(use_cache=False): ~129s total
  - pre_start + post_start: ~117s (WPS install ~80s + PPTX download + warm-up)
  - pre_task: ~12s (kill/reset/launch, "performance.pptx" found in ~2s)

## PDF Export Notes

- WPS "Export to PDF" works natively via Menu button → Export to PDF
- Default export filename: `performance.pdf` (strips `.pptx` extension from source filename)
- Default export path: `/home/ga/Documents/presentations/performance.pdf`
- Export produces valid PDF 1.7 with all 48 slides (~955KB)
- Export to PDF dialog: OK button at actual(1208, 798) on 1920×1080
- `wpspdf` CLI tool exists at `/opt/kingsoft/wps-office/office6/wpspdf` but requires DISPLAY (not headless)
- **Verified**: export_to_pdf task confirmed completable — PDF produced, 955,369 bytes, PDF 1.7
