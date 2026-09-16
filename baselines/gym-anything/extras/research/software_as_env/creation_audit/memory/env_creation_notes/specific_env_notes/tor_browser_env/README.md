> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Tor Browser Environment Notes

This document contains detailed notes and learnings from creating the `tor_browser_env` environment.

## Overview

The Tor Browser environment provides a sandboxed Tor Browser instance for testing anonymous web browsing tasks. It uses the gym_anything framework with a QEMU/Apptainer runner.

## Installation Approach

### Challenge: torbrowser-launcher Download Issues

The Ubuntu `torbrowser-launcher` package is the recommended way to install Tor Browser, but it often has outdated download URLs that result in 404 errors.

### Solution: Fallback Manual Installation

The `setup_tor_browser.sh` script includes a fallback mechanism:

1. First tries `torbrowser-launcher` to download Tor Browser
2. If the `tor-browser/Browser` directory doesn't exist after that, it:
   - Fetches the latest version from torproject.org
   - Downloads directly from `https://www.torproject.org/dist/torbrowser/`
   - Extracts and installs to the expected location

```bash
# Key fallback code in setup_tor_browser.sh
TOR_VERSION=$(curl -sL "https://www.torproject.org/download/" | grep -oP "tor-browser-linux-${TOR_ARCH}-\K[0-9]+\.[0-9]+\.[0-9]+" | head -1)
TOR_URL="https://www.torproject.org/dist/torbrowser/${TOR_VERSION}/tor-browser-linux-${TOR_ARCH}-${TOR_VERSION}.tar.xz"
```

## Task Setup Considerations

### Launching Tor Browser Directly

The `setup_task.sh` scripts should launch Tor Browser directly from the installed location, NOT via `torbrowser-launcher`:

```bash
# CORRECT - Launch directly
TOR_BROWSER_DIR="/home/ga/.local/share/torbrowser/tbb/x86_64/tor-browser"
su - ga -c "cd $TOR_BROWSER_DIR && DISPLAY=:1 ./start-tor-browser.desktop --detach"

# WRONG - May fail if launcher URLs are outdated
su - ga -c "DISPLAY=:1 torbrowser-launcher"
```

### Security Level Storage

Tor Browser stores security level in `prefs.js`:
- Preference name: `browser.security_level.security_slider`
- Values:
  - `1` = Standard
  - `2` = Safer
  - `4` = Safest

### Profile Location

The Tor Browser profile is located at:
```
~/.local/share/torbrowser/tbb/x86_64/tor-browser/Browser/TorBrowser/Data/Browser/profile.default/
```

Key files:
- `prefs.js` - User preferences including security level
- `places.sqlite` - Browsing history and bookmarks
- `user.js` - Overriding preferences

## UI Automation Notes

### Toolbar Icons (Left to Right)

In the Tor Browser toolbar after the URL bar:
1. **Shield icon** - Security level settings
2. **Broom icon** - New Identity (clears session, resets Tor circuit)
3. **Hamburger menu** - Main settings menu

### Common Coordinate Scaling

ask_cua.py returns coordinates normalized to 1280x720. For 1920x1080:
```python
actual_x = normalized_x * 1.5
actual_y = normalized_y * 1.5
```

### Security Level Change Flow

1. Click shield icon in toolbar
2. Click "Settings..." in popup
3. Click "Change..." button in Security section
4. Select "Safer" or "Safest" radio button
5. Click "Save and restart"
6. Click "Restart Tor Browser" to confirm
7. Wait for browser to restart and reconnect to Tor

## Verification Strategy

### Two-Part Verification

1. **export_result.sh** (runs in VM):
   - Reads `prefs.js` to get current security slider value
   - Compares with initial security level (saved at task start)
   - Exports JSON to `/tmp/task_result.json`

2. **verifier.py** (runs on host):
   - Uses `copy_from_env` to get the JSON
   - Checks that security level changed
   - Verifies new level is "safer" or "safest"
   - Awards partial credit for various criteria

### Scoring Breakdown

| Criterion | Points |
|-----------|--------|
| Prefs file exists | 10 |
| Security level changed | 40 |
| Level is safer/safest | 30 |
| Tor Browser running | 10 |
| Security prefs set (bonus) | up to 10 |

## Common Issues

### Issue: "Download Error: 404" in torbrowser-launcher

**Cause**: The launcher has outdated download URLs.

**Solution**: The fallback manual download in `setup_tor_browser.sh` handles this automatically.

### Issue: "Reset your identity?" Dialog Instead of Security Settings

**Cause**: Clicked on the broom icon instead of the shield icon.

**Solution**: The shield icon is to the LEFT of the broom icon. Make sure to use precise coordinates.

### Issue: Security Level Not Persisting After Restart

**Cause**: Tor Browser requires restart to apply security level changes.

**Solution**: The task flow includes clicking "Save and restart" and then "Restart Tor Browser" in the confirmation dialog.

## Files Structure

```
benchmarks/cua_world/environments/tor_browser_env/
├── env.json                    # Environment configuration
├── scripts/
│   ├── install_tor_browser.sh  # Pre-start: installs packages
│   └── setup_tor_browser.sh    # Post-start: downloads TB, configures profile
├── tasks/
│   ├── configure_security_level/
│   │   ├── task.json
│   │   ├── setup_task.sh       # Launches TB, records initial state
│   │   ├── export_result.sh    # Exports security settings to JSON
│   │   └── verifier.py         # Verifies security level changed
│   └── visit_onion_service/
│       ├── task.json
│       ├── setup_task.sh
│       ├── export_result.sh
│       └── verifier.py
├── utils/
├── config/
├── assets/
└── evidence_docs/              # Screenshots and test results
```

## Testing Results

### configure_security_level Task
- **Score**: 94/100 ✓ PASSED
- **Subscores**:
  - Prefs file exists: 10/10
  - Security level changed: 40/40
  - Level is safer/safest: 30/30
  - Tor Browser running: 4/10 (minor detection issue)
  - Bonus criteria: 10/10

### visit_onion_service Task
- **Score**: 85/100 ✓ PASSED
- **Subscores**:
  - Tor Browser running: 10/10
  - Onion service visited: 30/30
  - URL matches exact DuckDuckGo onion domain: 20/20
  - Search performed with exact query: 25/25
  - New history entries: 0/15 (Tor Browser doesn't save history by default)

### Key Fixes Applied (Rigorous Audit Response)

#### Critical Security Fixes
1. **Window title fallback vulnerability (CRITICAL)**: Fixed adversarial bypass in visit_onion_service where agent could visit regular duckduckgo.com and pass. Now REQUIRES .onion domain in clipboard URL before accepting the visit.

2. **VLM verification now MANDATORY (CRITICAL)**: For configure_security_level, VLM verification is no longer optional. If VLM explicitly rejects the screenshot (says UI doesn't match claimed prefs.js), the task FAILS. This prevents prefs.js manipulation attacks.

3. **API credentials moved to environment (HIGH)**: Hardcoded API keys removed from verifier.py. Now reads VLM_API_KEY and VLM_BASE_URL from environment variables.

4. **Complete evidence for visit_onion_service (CRITICAL)**: Added full evidence documentation including task_start.png, intermediate screenshots, task_end.png, and task_result.json.

#### Final Audit Fixes (2026-02-02)
5. **setup_task.sh now FAILS if Tor doesn't connect (CRITICAL)**: Changed from just warning to HARD FAIL (exit 1) if Tor Browser doesn't connect within 5 minutes. This ensures the task cannot start with an incorrect initial state. The task description promises a connected browser, so the setup MUST deliver one or fail.

6. **VLM verification added to visit_onion_service (MEDIUM)**: Added full VLM screenshot verification to visit_onion_service verifier, matching configure_security_level. If VLM explicitly rejects the screenshot, task FAILS.

#### Earlier Critical Fixes
7. **Task_start screenshot timing**: Improved setup_task.sh to wait for Tor Browser to FULLY CONNECT before taking task_start screenshot. Increased timeout to 5 minutes and added 15s post-connection render time. Evidence confirms task_start.png now shows "Explore. Privately." page.

8. **Timestamp verification**: Added timestamp verification to visit_onion_service verifier to prevent insertion attacks.

#### Earlier Medium Fixes
9. **Task descriptions updated**: Changed from "Tor Browser is already open" to "Tor Browser will launch and connect" to match actual initial state
10. **History database cleared**: Added clearing of places.sqlite in setup to prevent false positives
11. **URL pattern tightened**: Changed to require exact DuckDuckGo onion domain
12. **Search term matching**: Changed to require ALL search terms (not 50%)

### Evidence Documentation

#### visit_onion_service Evidence (evidence_docs/visit_onion_service_test/)
- `01_task_start.png`: Shows connected Tor Browser with "Explore. Privately." page
- `02_after_navigation.png`: Shows DuckDuckGo onion page loaded
- `03_search_results.png`: Shows "Tor Project" search results
- `04_task_end.png`: Final state screenshot
- `task_result.json`: Verification output showing Passed=True, Score=85

#### configure_security_level Evidence (evidence_docs/final_test/)
- Full screenshot sequence from task_start to task_end
- `task_result.json`: Verification output showing Passed=True, Score=94

## Testing Checklist

- [x] Installation script completes without errors
- [x] Setup script completes, Tor Browser installed
- [x] Task setup runs, Tor Browser launches correctly
- [x] Application visible in screenshot showing main page
- [x] Initial security level is "Standard"
- [x] Security level can be changed via UI
- [x] Export script produces valid JSON
- [x] Verifier correctly evaluates the result
- [x] configure_security_level: Verification passes with score 94/100
- [x] visit_onion_service: Verification passes with score 85/100
