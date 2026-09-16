> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# AndroidAPS Environment Notes

## Overview
AndroidAPS (AAPS) is an open-source artificial pancreas system for Type 1 Diabetes management. It runs on Android and connects to insulin pumps and CGM sensors to automate insulin delivery.

## Architecture
- **Base**: `android-avd-34` (AVD runner with Android 14 emulator)
- **APK**: Built from source (nightscout/AndroidAPS GitHub, `full` flavor, debug build)
- **Package name**: `info.nightscout.androidaps`
- **Main activity**: `info.nightscout.androidaps/.MainActivity`

## Build Requirements
- JDK 17
- Android SDK with platform 35 and build-tools 34.0.0
- Compile SDK: 35, Min SDK: 30, Target SDK: 30
- Build command: `./gradlew assembleFullDebug --no-daemon`
- APK output: `app/build/outputs/apk/full/debug/app-full-debug.apk`

## Key App Features Used
1. **Virtual Pump**: AndroidAPS has a built-in virtual pump that simulates insulin delivery without real hardware
2. **Random BG Source**: In demo mode, generates simulated CGM readings
3. **Local Profile**: Allows configuring basal rates, ISF, IC ratios
4. **Temp Targets**: Temporary glucose targets (exercise, eating soon, hypo)
5. **Setup Wizard**: Initial configuration walkthrough

## Real Data Sources
- **CGM Data**: Dexcom G6 export (10,000+ readings) from https://github.com/kjthorpe18/dexcom-data-scripts
- **Clinical Profile**: Based on published clinical guidelines:
  - ISF calculated via 1800-rule (UCSF Diabetes Education)
  - IC ratio via 500-rule (ADA guidelines)
  - Basal rates from published dawn phenomenon patterns
  - TDD of 40U typical for adult with T1D (~70kg)

## App-Specific Quirks
1. **Permissions**: Needs location, Bluetooth, and notification permissions granted
2. **Battery optimization**: Must be whitelisted (`dumpsys deviceidle whitelist +info.nightscout.androidaps`)
3. **Setup wizard**: First launch shows a multi-step wizard; tasks may need to work with or around it
4. **Notification permission dialog**: Android 13+ shows a dialog on first launch
5. **Objectives system**: AAPS has a progressive unlock system; virtual pump allows bypassing hardware-dependent objectives

## Task Design Notes
- Tasks interact with the AndroidAPS UI through the Android emulator
- The emulator runs with software rendering (`swiftshader_indirect`)
- Without KVM, performance is slow but functional
- UI elements can be verified via `uiautomator dump`
- The app's hamburger menu provides access to most configuration screens

## Resource Requirements
- CPU: 4 cores (emulator + Android OS)
- RAM: 8 GB (emulator needs ~4GB)
- Network: Required for initial APK build, not needed at runtime
- Disk: ~2GB for SDK + system image + APK
