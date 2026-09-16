> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# QField GIS Environment — Creation Notes

## Bulk Task Fix (2026-03-16)

### Issues Fixed
1. **3 tasks rewritten** (`restore_missing_iso_codes`, `deduplicate_overlapping_features`, `sar_coordinate_handoff`): Were written as host-side scripts using `#!/bin/bash` + `adb pull/push` + `python3`. Rewrote as proper Android shell scripts using `#!/system/bin/sh` + `/system/bin/sqlite3`.
2. **24 task.json hook paths fixed**: Some used `/workspace/tasks/...` (Linux path) instead of `sh /sdcard/tasks/<task>/setup_task.sh`. Some pointed to wrong files (`digitize_cable_route` → wrong path, `tag_high_latitude_infra` → generic path).
3. **18 setup scripts**: Removed `set -e` (causes failures on Android's mksh shell).
4. **5 export_result.sh scripts**: Fixed shebangs, removed `adb` references, fixed `/tmp/` paths.
5. **seed_tasks.json**: Removed 2 tasks (`open_project`, `add_survey_point`) whose directories don't exist.
6. **Verified sqlite3 available**: `/system/bin/sqlite3` confirmed present on Android API 34.

### Tests Performed
- `deduplicate_overlapping_features` (rewritten): QField loads, map visible, pre_task hook runs successfully
- `restore_vandalized_capital_names` (hook fix): QField loads with world capitals map, ready for agent
- Both showed QField in foreground with capital cities visible

---

## Application
- **App**: QField v3.4.6 (mobile GIS for Android)
- **Package**: `ch.opengis.qfield`
- **APK**: `qfield-v3.4.6-android-x64.apk` (91MB x86_64 variant)
- **APK URL**: https://github.com/opengisch/QField/releases/download/v3.4.6/qfield-v3.4.6-android-x64.apk
- **AVD**: `android-avd-34` + `google_apis_playstore` variant, x86_64 ABI

## Key Architecture