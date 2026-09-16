> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Screaming Frog SEO Spider Environment Notes

## Overview

Screaming Frog SEO Spider is a website crawler and SEO auditing tool. This environment provides tasks for crawling websites, exporting reports, and finding broken links.

## Installation

### Key Points

1. **Download URL**: https://www.screamingfrog.co.uk/seo-spider/screamingfrogseospider_23.2_all.deb
2. **Package Type**: .deb package (Debian/Ubuntu)
3. **Binary Location**: `/usr/bin/screamingfrogseospider`
4. **Config Directory**: `~/.ScreamingFrogSEOSpider/`

### Dependencies

- Java (bundled with the application)
- GUI libraries (GTK, etc.)
- wmctrl, xdotool for window management
- python3 for verification scripts

## First-Run Behavior

### EULA Dialog

Screaming Frog shows an End User License Agreement dialog on first launch. This must be accepted before the application is usable.

**Handling in setup_task.sh:**
```bash
eula_window=$(su - ga -c "DISPLAY=:1 xdotool search --name 'License Agreement' 2>/dev/null | head -1")
if [ -n "$eula_window" ]; then
    echo "EULA dialog detected, accepting..."
    su - ga -c "DISPLAY=:1 xdotool windowactivate --sync $eula_window 2>/dev/null" || true
    sleep 1
    su - ga -c "DISPLAY=:1 xdotool key Return" || true
    sleep 3
    sleep 15  # Wait for app to load after EULA
fi
```

### Loading Time

After EULA acceptance, the application takes 10-15 seconds to fully load. The loading screen shows a progress bar.

## Process Detection

### Issue

The process name varies in case:
- Binary: `screamingfrogseospider`
- Display name: `ScreamingFrogSEOSpider`

### Solution

Use case-insensitive matching with `pgrep -fi`:

```bash
# CORRECT - case insensitive
pgrep -fi "screamingfrog" > /dev/null 2>&1

# WRONG - may miss processes
pgrep -f "ScreamingFrogSEOSpider" > /dev/null 2>&1
```

## Window Title Detection

### Crawl Detection

When a crawl is in progress or complete, the window title shows the crawled URL:
- Format: `http-<domain>- - Screaming Frog SEO Spider 23.2 (Unlicensed)`
- Example: `http-localhost-8080- - Screaming Frog SEO Spider 23.2 (Unlicensed)`

### Detection Logic

```bash
SF_WINDOW=$(DISPLAY=:1 wmctrl -l | grep -i "screaming frog\|seo spider" | head -1)
if echo "$SF_WINDOW" | grep -qi "http\|crawl\|crawler-test"; then
    CRAWL_DETECTED="true"
fi
```

## URL Input

### Auto-Focus Behavior

After the window is activated, typing will automatically go to the URL input field. No need to click on the field first.

### Interaction Pattern

```bash
# 1. Activate window
xdotool search --name "Screaming Frog" windowactivate --sync

# 2. Triple-click to select URL field, then type
xdotool mousemove 480 111 click --repeat 3 1
xdotool type "https://crawler-test.com/"

# 3. Press Escape to close any autocomplete dropdown
xdotool key Escape

# 4. Press Enter to start crawl
xdotool key Return
```

## Test Website (REAL DATA)

This environment uses **real public websites** for testing, NOT handwritten sample data:

### Primary Test Website: https://crawler-test.com/

This is a real public website specifically designed for SEO crawler testing. It contains:
- Multiple HTML pages with various SEO test cases
- Intentional broken links at https://crawler-test.com/links/broken_links
- Canonical tag tests, redirects, and other SEO scenarios
- No authentication required - freely accessible

### Why Real Data?

The gym_anything framework requires real-world data to ensure:
1. Agents interact with realistic scenarios
2. Verification tests meaningful real-world behavior
3. Tasks represent actual use cases

**Do NOT use handwritten/mock HTML pages.**

## Verification Strategy

### Two-Part Verification

1. **Export Script** (runs in container): Checks process state, window title, and export files
2. **Verifier** (runs on host): Uses `copy_from_env` to read exported JSON

### Scoring Criteria

| Criterion | Points | Detection Method |
|-----------|--------|------------------|
| SF Running | 15 | `pgrep -fi screamingfrog` |
| Crawl Detected | 25 | Window title contains URL |
| URLs Found | 35 | Export CSV or window title |
| Export Created | 25 | New CSV in exports directory |

### Passing Threshold

Score >= 50 AND screaming_frog_running = true

## Common Issues

### Issue: Dropdown Menus Opening Unexpectedly

The Screaming Frog interface has many dropdown menus that open on click. Be careful about click coordinates.

**Solution**: Use precise coordinates from ask_cua.py and press Escape to close dropdowns.

### Issue: App Not Launching

Check if the binary path is correct. The .deb installation puts it in `/usr/bin/screamingfrogseospider`.

**Solution**: Use `command -v screamingfrogseospider` to find the correct path.

### Issue: Export Files Not Created

Screaming Frog only creates export files when the user explicitly exports data via the menu.

**Solution**: Detect crawl success via window title rather than export files for basic crawl tasks.

## Tasks

### crawl_website (Easy)
- Crawl https://crawler-test.com/
- Verify crawl detected via window title (shows "https-crawler-test-com-")

### export_crawl_report (Medium)
- Crawl https://crawler-test.com/ and export to CSV
- Verify CSV file created with crawl data

### find_broken_links (Medium)
- Crawl https://crawler-test.com/links/broken_links
- Identify 404 errors using Response Codes tab
- Real website has intentional broken links for testing

## Resource Requirements

- **CPU**: 4 cores recommended
- **Memory**: 8GB (Java application with web crawling)
- **Network**: Required for application download
- **GPU**: Not required
