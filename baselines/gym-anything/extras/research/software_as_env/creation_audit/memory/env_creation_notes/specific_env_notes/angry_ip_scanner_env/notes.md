> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Angry IP Scanner Environment Notes

## Application Details
- **Binary**: `/usr/bin/ipscan` (shell wrapper that launches Java)
- **Actual Java command**: `/bin/java --add-opens java.base/java.net=ALL-UNNAMED -jar /usr/lib/ipscan/ipscan-linux64-3.9.3.jar`
- **GUI Toolkit**: SWT (Eclipse Standard Widget Toolkit) on GTK3
- **Java Version Required**: OpenJDK 17+

## Installation
- Download `.deb` from GitHub releases: `https://github.com/angryip/ipscan/releases/download/3.9.3/ipscan_3.9.3_amd64.deb`
- Install with `dpkg -i` then `apt-get install -f -y` for dependencies
- Requires: `openjdk-17-jre`

## Configuration / Preferences
- Stored in: `~/.java/.userPrefs/ipscan/` (Java Preferences API)
- Key subdirectories: `gui/`, `scanner/`, `favorites/`, `openers/`, `comments/`, `mac/`
- Format: XML files (`prefs.xml` in each directory)

### Important Preference Keys
| Path | Key | Values | Purpose |
|------|-----|--------|---------|
| gui/prefs.xml | firstRun | true/false | First-run dialog trigger |
| gui/prefs.xml | versionCheckEnabled | true/false | Startup update check |
| gui/prefs.xml | askScanConfirmation | true/false | Confirm before scanning |
| gui/prefs.xml | displayMethod | ALL/ALIVE/PORTS | Results filter |
| scanner/prefs.xml | portString | comma-separated | Ports to scan |
| scanner/prefs.xml | maxThreads | integer | Max concurrent threads |
| scanner/prefs.xml | pingingMethod | 0-3 | ICMP=0, UDP=1, TCP=2, Combined=3 |
| prefs.xml | language | en, etc. | UI language |

## SWT-Specific Quirks

### Dialog Dismissal
- **xdotool key Escape** does NOT work on SWT dialogs
- **wmctrl -c "Dialog Title"** DOES work
- Always use `wmctrl -c` for closing SWT dialogs programmatically

### Tab Controls
- xdotool synthetic mouse clicks often fail to register on SWT tab widgets
- VNC-level mouse events (through the framework) work correctly
- Keyboard tab switching (Ctrl+PageDown) does NOT work in SWT CTabFolder
- Agent interaction through the framework's VNC-based action injection works for clicking tabs

### Menu Access
- **F10** opens the first menu (Scan)
- Arrow keys navigate between menus and menu items
- Keyboard shortcuts work: Shift+Ctrl+P (Preferences), Shift+Ctrl+O (Fetchers), Ctrl+S (Export), Ctrl+T (Statistics)

## Known Dialogs
| Dialog | When | Title | How to Dismiss |
|--------|------|-------|----------------|
| Getting Started | First launch or if prefs not fully saved | "Getting Started" | `wmctrl -c "Getting Started"` |
| Scan Statistics | After scan completes | "Scan Statistics" | `wmctrl -c "Scan Statistics"` or click Close |
| Preferences | Tools > Preferences | "Preferences" | Cancel/OK buttons |
| Fetchers | Tools > Fetchers | "Fetchers" | Cancel/OK buttons |

## Process Detection
- Use `pgrep -c -f ipscan` (count mode to avoid self-match)
- Two processes: shell wrapper (`/bin/sh /usr/bin/ipscan`) and JVM (`/bin/java ... ipscan-linux64-3.9.3.jar`)
- Do NOT use `pgrep java` as it matches any JVM process

## Network in QEMU VM
- VM gets NAT network: 10.0.2.0/24
- Gateway: 10.0.2.2
- VM IP: 10.0.2.15
- DNS: 10.0.2.3
- Default scan range auto-detected from VM's network interface

## Real Scan Targets
- SSH on port 22 (openssh-server)
- Apache HTTP on port 80 (apache2)
- Scan of 10.0.2.0/24 finds ~4 alive hosts (VM, gateway, DNS, DHCP)
