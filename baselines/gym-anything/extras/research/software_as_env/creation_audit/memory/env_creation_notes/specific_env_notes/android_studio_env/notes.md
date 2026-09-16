> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Android Studio Environment Notes

## Installation Details

### Android Studio Version
- Android Studio Ladybug 2024.2.1 Patch 2
- Build: AI-242.23339.11.2421.12550806
- Config directory: `~/.config/Google/AndroidStudio2024.2/`

### Download URLs
- IDE: `https://redirector.gvt1.com/edgedl/android/studio/ide-zips/2024.2.1.11/android-studio-2024.2.1.11-linux.tar.gz`
- Command-line tools: `https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip`

### Key Paths in VM
| Path | Description |
|------|-------------|
| `/opt/android-studio/` | Android Studio IDE |
| `/opt/android-studio/bin/studio.sh` | IDE launcher |
| `/opt/android-sdk/` | Android SDK root |
| `/opt/android-sdk/cmdline-tools/latest/bin/` | SDK manager |
| `/home/ga/.config/Google/AndroidStudio2024.2/` | User config |
| `/home/ga/AndroidStudioProjects/` | Default project directory |

## First-Run Dialog Suppression

Android Studio has many first-run dialogs. These are suppressed via:

1. **EULA/Privacy**: Written to `~/.config/Google/AndroidStudio2024.2/accepted`
2. **Data sharing**: Written to `~/.config/Google/consentOptions/accepted`
3. **Java Preferences**: Written to `~/.java/.userPrefs/jetbrains/`
4. **VM Options**: `-Djb.privacy.policy.text=<!--999.999-->` and `-Djb.consents.confirmation.enabled=false`
5. **idea.properties**: `idea.initially.ask.config=false`
6. **Tips of the day**: Disabled in `ide.general.xml`
7. **Trust Project**: Pre-configured trusted paths in `trusted-paths.xml` and `trustedProjects.xml`

## Timing Characteristics

| Phase | Duration | Notes |
|-------|----------|-------|
| Pre-start (install) | ~700s | Downloads IDE (~1.4GB) + SDK components |
| Post-start (setup) | ~80s | Config files + IDE launch + 120s wait |
| Pre-task | ~15-30s | Project copy + IDE wait + focus |
| Android Studio launch | ~20s | From process start to window visible |

### Important: Window Detection
- The post_start hook waits up to 120s for the window, but during first boot the IDE may not be launched until the pre_task hook
- Use `wmctrl -l | grep -qi "android\|studio\|welcome"` to detect the window
- The window title is "Welcome to Android Studio" when no project is open

## SDK License Acceptance
Pre-created license files in `$ANDROID_SDK_ROOT/licenses/`:
```
android-sdk-license: 24333f8a63b6825ea9c5514f83c2829b004d1fee
android-sdk-license: d975f751698a77e662f1cd747457a47e13b58f7b
android-sdk-preview-license: 84831b9409646a918e30573bab4c9c91346d8abd
```
Also `yes | sdkmanager --licenses` for any additional licenses.

## 32-bit Library Requirements
Android SDK tools require 32-bit libraries:
```bash
dpkg --add-architecture i386
apt-get install -y libc6:i386 libncurses5:i386 libstdc++6:i386 lib32z1 libbz2-1.0:i386
```

## Project Data

### SunflowerApp (Working Project)
- Based on Google's Android Sunflower sample
- Package: `com.google.samples.apps.sunflower`
- Features: Plant data class, PlantRepository singleton, 5 sample plants
- Build: AGP 8.2.0, Kotlin 1.9.22, compileSdk 34

### BrokenApp (4 Intentional Errors)
1. `MainActivity.kt`: Missing `import android.os.Bundle`
2. `Plant.kt`: `growZoneNumber: String` but compared with `Int` in `isInGrowZone()`
3. `PlantRepository.kt`: Unclosed brace in `addPlant()` function
4. `app/build.gradle.kts`: Uses `retrofit2` in code but dependency is commented out

### NotepadApp (Testing Target)
- Package: `com.example.notepad`
- Has `Note`, `NoteValidator`, `NoteFormatter` classes
- NO test files (task is to add them)
- JUnit 4.13.2 already in test dependencies

### CalculatorApp (Refactoring Target)
- Package: `com.example.calculator`
- `CalcEngine` class with poor names: `doAdd`, `doSub`, `doMul`, `doDiv`, `doMod`
- Target: Rename to `Calculator` with `add`, `subtract`, `multiply`, `divide`, `modulo`

## Verification Gotchas

1. **Gradle wrapper**: Projects need `gradlew` to be executable (`chmod +x`)
2. **Build cache**: `.gradle/` directory indicates Gradle sync happened
3. **IDE markers**: `.idea/` directory indicates project was opened in IDE
4. **Copy permissions**: Use the temp-file-then-copy pattern for writing JSON results
5. **Environment variables**: Gradle builds need `JAVA_HOME`, `ANDROID_SDK_ROOT`, `ANDROID_HOME`

## Testing Results

### Baseline Scores (no agent action)
| Task | Score | Notes |
|------|-------|-------|
| create_new_project | 0 | WeatherTracker doesn't exist |
| import_gradle_project | 70 | Source files exist, .idea/.gradle missing |
| fix_build_errors | 0 | All 4 bugs present, build fails |
| add_unit_test | 0 | No test files exist |
| refactor_rename_class | 0 | CalcEngine not renamed |

### After Agent Action (import_gradle_project)
- Score: 100/100 (all 6 criteria pass)
- Method: Click Open button, type path, press Enter
- .idea/ and .gradle/ directories created by Android Studio

## Critical Installation Fix: needrestart

During apt-get install, the `needrestart` package can restart the SSH daemon,
breaking connectivity. Must suppress with:
```bash
export NEEDRESTART_MODE=l
mkdir -p /etc/needrestart/conf.d
cat > /etc/needrestart/conf.d/99-noninteractive.conf <<'EOF'
$nrconf{restart} = 'l';
$nrconf{ui} = 'stdio';
$nrconf{kernelhints} = 0;
EOF
```

## QEMU Process Lifecycle

Background bash tasks (run_in_background=true) send SIGTERM to child QEMU
processes when the shell exits. For interactive testing, use nohup+disown:
```bash
nohup python3 -u script.py > /tmp/output.log 2>&1 &
disown
```
