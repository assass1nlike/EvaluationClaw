> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Subway Surfers Environment Notes

## Overview

Subway Surfers is an endless runner mobile game. This environment was created to benchmark agents on real-time game control tasks.

- **Package**: `com.kiloo.subwaysurf`
- **APK Size**: ~216MB
- **Type**: Real-time endless runner
- **Controls**: Swipe gestures (up/down/left/right)

## Key Learnings

### 1. APK Installation

**Problem**: Using `pm install` from `/sdcard/` is very slow for large APKs (216MB).

**Solution**: Use the `apks` field in env.json which uses `adb install` streaming:
```json
{
  "apks": [
    "benchmarks/cua_world/environments/subway_surfers_env/scripts/apks/subway_surfers.apk"
  ]
}
```

### 2. Game Loading Time

**Problem**: Subway Surfers takes 40-60 seconds to fully load after launch.

**Solution**: Add adequate sleep in the post_start hook:
```bash
# Wait for game to fully load
echo "Waiting for game to load (60 seconds)..."
sleep 60
```

### 3. Age Verification Dialog

**Problem**: Game shows age verification dialog on first launch with an age picker.

**Solution**: Tap the right arrow multiple times to increment age:
```bash
# Right arrow at (900, 1400) - tap 25 times for age 25
for i in $(seq 1 25); do
    input tap 900 1400
done
sleep 2

# Confirm button at (540, 1600)
input tap 540 1600
```

### 4. Immersive Mode Notification

**Problem**: Android shows "Swipe down to exit fullscreen" notification that blocks UI.

**Solution**: The AVD runner now automatically applies settings:
```bash
settings put secure immersive_mode_confirmations confirmed
settings put global policy_control "immersive.full=*"
```

### 5. Hook Timeout

**Problem**: Post-start hook timed out at 60 seconds, but setup needs ~100 seconds.

**Solution**: Framework was updated to use 180-second timeout for Android hooks.

### 6. Hook Path Duplication

**Problem**: Hook path was specified as `sh /sdcard/tasks/.../script.sh` but framework also adds `sh` prefix, resulting in `sh sh /path`.

**Solution**: In env.json, specify just the path without `sh` prefix:
```json
{
  "hooks": {
    "post_start": "/sdcard/tasks/score_1000_points/launch_game.sh"
  }
}
```

## UI Coordinates (1080x2400 resolution)

### Age Verification Screen
- Right arrow (increment age): (900, 1400)
- Confirm button: (540, 1600)

### Main Menu
- Tap to Play area: (540, 2100)
- Play button: (540, 1800)

### Pause/Mission Screen
- Quit button: (216, 2310)
- Resume button: (780, 2310)

### Gameplay Controls (Swipe)
- Jump (swipe up): `input swipe 540 1600 540 1000 150`
- Roll (swipe down): `input swipe 540 1000 540 1600 150`
- Move left: `input swipe 700 1200 300 1200 150`
- Move right: `input swipe 300 1200 700 1200 150`

## Verification

The verifier extracts scores from the UI dump by:
1. Finding all `text="..."` attributes
2. Extracting numbers >= 100 (to filter out non-scores)
3. Comparing the highest score against target (1000)

Score appears in:
- Gameplay: Top-right corner (e.g., "000123")
- Game over screen: Score display
- Mission screen: Progress text (e.g., "43/500")

## File Structure

```
benchmarks/cua_world/environments/subway_surfers_env/
├── env.json                    # Main config (uses apks field)
├── scripts/
│   ├── download_apk.sh         # Downloads APK from APKPure
│   └── apks/
│       └── subway_surfers.apk  # 216MB APK
├── tasks/
│   └── score_1000_points/
│       ├── task.json           # Task definition (target: 1000 points)
│       ├── launch_game.sh      # Post-start hook (age verification, launch)
│       ├── setup_task.sh       # Pre-task hook
│       ├── export_result.sh    # Post-task hook (UI dump)
│       └── verifier.py         # Score extraction and verification
├── artifacts/                  # Episode outputs
└── test_subway_surfers.py      # Test script
```

## Test Results

All tests pass:
- Framework initialization: PASS
- Environment reset: PASS (~154s)
- APK installation: PASS (via adb install)
- Screenshot capture: PASS
- VNC server: PASS
- Swipe input: PASS
- Framework step: PASS
- UI dump: PASS

## Tips for Similar Games

1. **Loading time**: Always account for game loading (30-90 seconds)
2. **First-run dialogs**: Map out all dialogs and their button positions
3. **Verification**: Use game over screens for stable verification
4. **Input timing**: Add small delays between inputs (0.5-1s)
5. **Swipe duration**: Use 150-200ms for natural swipes
6. **Memory**: Games need 6GB+ RAM - set `mem_gb: 6` in resources
