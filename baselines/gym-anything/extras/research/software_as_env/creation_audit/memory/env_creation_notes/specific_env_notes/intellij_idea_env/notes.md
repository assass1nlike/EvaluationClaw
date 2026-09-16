> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# IntelliJ IDEA Community Edition Environment Notes

## Overview

Environment for IntelliJ IDEA Community Edition, a Java IDE by JetBrains.
Used for tasks involving Java project creation, build error fixing, code refactoring,
debugging, and unit testing.

## Installation Details

### IntelliJ IDEA CE
- **Version**: 2024.3.1.1 (with fallback to 2024.3)
- **Download**: `https://download.jetbrains.com/idea/ideaIC-<VERSION>.tar.gz`
- **Install path**: `/opt/idea`
- **Launcher**: `/opt/idea/bin/idea.sh` (symlinked to `/usr/local/bin/idea`)
- **Bundles JetBrains Runtime (JBR)**: based on OpenJDK 21

### Java / JDK
- **System JDK**: OpenJDK 17 (`apt-get install openjdk-17-jdk`)
- **JAVA_HOME**: `/usr/lib/jvm/java-17-openjdk-amd64`
- IntelliJ uses its bundled JBR to run itself; OpenJDK 17 is for project compilation

### Maven
- Installed via `apt-get install maven`
- Pre-warmed local repository with JUnit 4.12 and Joda-Time 2.9.2

## Configuration

### Suppressing First-Run Dialogs
1. Pre-create `~/.config/JetBrains/IdeaIC<version>/` directory
2. Write consent file to `~/.config/JetBrains/consentOptions/accepted`
3. Configure `options/ide.general.xml` to disable tips on startup
4. Set `idea64.vmoptions` with `-Dnosplash=true`

### Version-Dependent Paths
The config directory includes the version number: `IdeaIC2024.3`.
The setup script attempts to detect this from the installation.
If the version changes, update the detection logic in `setup_intellij.sh`.

## Tasks

| Task | Difficulty | Description | Key Verification |
|------|-----------|-------------|------------------|
| create_maven_project | Easy | Create Spring gs-maven project from scratch | pom.xml, Java files, .class files |
| fix_build_errors | Medium | Fix 3 injected errors in gs-maven project | Fixed sources, successful build |
| refactor_code | Medium | Rename method/params, extract method | Code structure, compilation |
| debug_fix_bug | Hard | Debug and fix division-by-zero bug | Source fix, all tests pass |
| add_junit_tests | Easy | Add JUnit dependency and write tests | pom.xml dependency, test file, test results |

## Data Sources

All task data is based on real open-source Java projects:
- **gs-maven**: Spring's "Getting Started with Maven" guide (`spring-attic/gs-maven`)
- **refactor-demo**: Based on LableOrg `java-maven-junit-helloworld`
- **calculator**: Based on Devskiller `devskiller-sample-maven-calculator`
- **calculator-test**: Based on kranonit `calculator-unit-test-example-java`

## Known Issues and Quirks

### IntelliJ Startup Time
IntelliJ takes 10-15 seconds to start and index a project. Tasks that open
projects should wait at least 15 seconds before the agent begins interacting.

### Memory Requirements
IntelliJ needs at least 2GB heap (configured in `idea64.vmoptions`).
The environment is configured with 8GB total RAM.

### Maven Dependency Resolution
First-time Maven builds require network access to download dependencies.
The install script pre-warms common dependencies (JUnit, Joda-Time) to reduce
task execution time.

### Welcome Screen vs Project Window
When IntelliJ starts with a project path argument, it may either show the
Welcome screen or directly open the project. The setup script handles both cases.

### File Permission Issues
All project files must be owned by `ga:ga`. The setup scripts use `chown -R ga:ga`
after copying project data.

## Verification Pattern

All tasks use the two-part verification pattern:
1. **export_result.sh** (runs in VM): Collects data, runs Maven if needed, saves to `/tmp/task_result.json`
2. **verifier.py** (runs on host): Uses `copy_from_env` to read files from VM

Key verification approaches:
- Parse `pom.xml` for Maven project structure
- Read Java source files for expected code patterns
- Check `.class` files for Java magic bytes (`0xCAFEBABE`)
- Parse Surefire XML reports for test results

## Learnings from Interactive Testing (Phase 6)

### Version Detection
- The initial approach of parsing jar filenames in `/opt/idea/lib/` failed because IntelliJ 2024.3+ doesn't use `idea-<version>.jar` naming.
- **Solution**: Parse `build.txt` (e.g., `IC-243.22562.218`) where major number `243` maps to year `2024`, minor `3`.
- Formula: `year = major / 10 + 2000`, `minor = major % 10`

### EULA / First-Run Dialogs
- IntelliJ 2024.3 requires accepting the End User Agreement on first launch.
- Pre-creating config directories and consent files alone was NOT sufficient.
- The EULA dialog caused IntelliJ to crash with a `SEVERE` error from `EuaKt$prepareShowEuaIfNeededTask`.
- **Solution**: Add JVM options to bypass:
  - `-Djb.privacy.policy.text=<!--999.999-->` (pretends policy is already accepted)
  - `-Djb.consents.confirmation.enabled=false` (disables consent prompts)
  - `-Didea.initially.ask.config=false` (skips initial config wizard)

### Process Survival
- Using `su - ga -c "... &"` to launch IntelliJ in background caused the process to be killed when the setup script (bash) exited due to `set -e`.
- **Solution**: Use `nohup` in the launch command: `su - ga -c "DISPLAY=:1 JAVA_HOME=... nohup /opt/idea/bin/idea.sh > /tmp/intellij_startup.log 2>&1 &"`

### Test Results (Baseline Scores)
Baseline scores confirm tasks are correctly configured:
- **create_maven_project**: 0/100 (nothing created yet - expected)
- **fix_build_errors**: 0/100 (all 3 bugs still present - expected)
- **refactor_code**: 25/100 (code unmodified but existing code compiles - expected)
- **debug_fix_bug**: 64/100 (4/5 tests pass, division-by-zero test fails - expected)
- **add_junit_tests**: 0/100 (no JUnit dependency or tests - expected)

### Runner API Notes
- Use `env._runner.exec_capture(cmd)` instead of paramiko SSH for running commands
- Use `env._runner.copy_from(remote, local)` to copy files from VM
- Access ports via `env._runner.ssh_port` and `env._runner.vnc_port`
- Process checks with `ps aux | grep` may return exit code 1 when empty, requiring paramiko fallback
- `env.step([{"type": "noop"}], mark_done=True)` triggers post_task hook + verification

### CUA Integration
- `ask_cua.py` works correctly for verifying GUI state
- Coordinates are normalized to 1280x720 - need scaling for actual 1920x1080 resolution
- CUA correctly identified IntelliJ Welcome screen with version, sidebar options, and action buttons

### VLM Verification (Phase 7 Addition)
- All 5 verifiers now include VLM-based trajectory verification alongside programmatic checks
- Shared utility `vlm_verify_intellij_task()` in `utils/intellij_verification_utils.py`
- Uses `sample_trajectory_frames()`, `get_first_screenshot()`, `get_final_screenshot()` from `gym_anything.vlm`
- VLM checklist items are task-specific (6 items per task covering IDE state, code changes, test results)
- VLM contributes up to 10 bonus points when >= 60% of checklist items pass
- VLM verification is wrapped in try/except so it gracefully degrades when VLM is unavailable
- Follows patterns from `extras/research/software_as_env/creation_audit/memory/env_creation_notes/vlm_checklist_patterns.md` and `09_verification_patterns.md`

### Interactive Testing with ask_cua.py (Phase 6 - 2026-01-29)
- Successfully completed `create_maven_project` task interactively using CUA guidance
- **Workflow**: Screenshot → ask_cua.py → xdotool action → repeat
- **CUA coordinate scaling**: Must convert from 1280x720 (CUA output) to 1920x1080 (actual resolution)
  - Formula: `actual_x = cua_x * 1920 / 1280`, `actual_y = cua_y * 1080 / 720`
- **xdotool reliability**: Good for clicks and single keypresses; unreliable for multi-line text typing (characters get dropped)
  - Workaround: Write file contents via shell, use xdotool only for UI navigation
- **Alt+Insert shortcut**: More reliable than right-click context menus for creating new files
- **Score improvement**: Task went from 0/100 (baseline) to 65/100 (after interactive completion)
- **Evidence saved**: `evidence_docs/interactive_test_final.png`, detailed CUA interaction log in README.md
