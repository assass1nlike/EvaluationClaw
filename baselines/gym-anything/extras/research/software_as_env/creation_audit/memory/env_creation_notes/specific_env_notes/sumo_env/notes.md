> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# SUMO Environment - Creation Notes

## Application Details
- **SUMO v1.26.0** (Eclipse SUMO, Simulation of Urban Mobility)
- PPA: `ppa:sumo/stable` (Ubuntu)
- Packages: `sumo`, `sumo-tools`, `sumo-doc`
- `SUMO_HOME=/usr/share/sumo`
- GUI toolkit: FOX (not GTK/Qt)

## Installation Notes
- PPA install is the simplest method on Ubuntu (~60-70s)
- `sumo-doc` installs tutorial scenarios and examples under `$SUMO_HOME/docs/`
- All three GUI tools (`sumo-gui`, `netedit`, `sumo`) install from the `sumo` package
- No build-from-source needed; PPA version is current (1.26.0)
- Required automation tools: `xdotool`, `wmctrl`, `scrot`, `imagemagick`, `xclip`, `python3-pyautogui`

## Key GUI Behaviors

### sumo-gui
- Opens with loaded scenario in paused state (no `--start` flag)
- **Do NOT use `--start`**: Simulation runs at max speed, finishing before agent can interact
- `--delay N`: adds N ms delay between steps (100-200 for visible movement), but not needed since agent controls playback
- When simulation completes, shows "Simulation ended" dialog with Yes/No buttons
- **Keyboard shortcuts**:
  - `Ctrl+A`: Start/pause simulation (most reliable method)
  - `Ctrl+S`: Single step
  - `Ctrl+Q`: Quit
  - `F9`: Open View Settings / Edit Visualization dialog
  - `Shift+V`: Open Vehicle Chooser (Locate > Vehicles)
- Right-click on vehicles/junctions for context menus
- Vehicle context menu items: "Show Current Route" (highlights in green), "Show Parameters" (opens dialog)

### netedit
- Default mode: "Inspect" (shows properties when clicking elements)
- **Mode switching keyboard shortcuts**: I=Inspect, E=Edge, C=Connect, T=Traffic lights, A=Additionals
- Network file loaded with `-s` flag (not positional argument)
- Additional files loaded with `-a` flag
- **Save shortcuts**:
  - `Ctrl+S`: Save network
  - `Ctrl+Shift+A`: Save additionals
  - `Ctrl+Shift+K`: Save TLS programs
- Traffic light mode: Press 'T', click on junction to see phase editor
- Additional mode: Press 'A', select element type from dropdown in left panel

### FOX Toolkit Quirks
- Text fields are narrow and truncate long values (e.g., "new_detector_1" displays as "detector_1")
- **Verification**: Use `xclip -selection clipboard -o` after Ctrl+A (select all) + Ctrl+C to verify actual field contents
- Dropdowns are tree-style: click to open, then click exact option text
- `pyautogui.typewrite()` doesn't handle underscores well — use `xdotool type --clearmodifiers` instead
- Element type dropdowns in netedit require precise coordinate clicks

## Data
- Used DLR-TS/sumo-scenarios GitHub repository (official SUMO scenarios)
- **Bologna Acosta**: Real-world network from Bologna, Italy (Acosta area)
  - 112 nodes, 117+ edges, ~2MB total
  - Includes: network, routes, bus routes, detectors, traffic lights, vehicle types
  - ~672 vehicles in full simulation run
  - Simulation duration: 0 to ~5655 seconds
- **Bologna Pasubio**: Real-world network from Bologna, Italy (Pasubio area)
  - Grid-like road layout (different from Acosta's irregular streets)
  - Similar file set and size

## Interactive Testing Findings

### run_simulation Task
- F9 opens View Settings dialog reliably
- Vehicles tab > Color dropdown: change from "given vehicle/type/route color" to "by speed"
- After clicking OK and starting sim (Ctrl+A), vehicles appear color-coded
- Screenshot via `scrot /home/ga/SUMO_Output/speed_coloring.png`

### change_traffic_light_phase Task
- Press 'T' to enter Traffic Light mode
- Click any red/dark-red junction node to open phase editor
- Phase table has "dur" column — click the cell, type new value (45), press Enter
- Save via Ctrl+Shift+K (not Ctrl+S, which saves the network file)

### add_vehicle_detector Task
- Press 'A' for Additional mode
- Element type dropdown: select "E1 inductionLoop" (may need to scroll)
- Set id via triple-click on field + `xdotool type --clearmodifiers "new_detector_1"`
- Period field: default or set to 300
- File field: type "new_detector_output.xml"
- **Placement**: Must click on a lane. At default zoom, lanes are very thin — zoom in for accuracy
- Successful placement: id field auto-increments (e.g., "e1_0" appears)
- Save: Ctrl+Shift+A
- Verify: grep for id in additionals XML file

### inspect_vehicle_route Task
- Start sim with Ctrl+A, wait a few seconds for vehicles to spawn
- Pause with Ctrl+A again
- **Problem**: Vehicles are tiny at default zoom — right-clicking often hits underlying lane or detector
- **Solution**: Use Vehicle Chooser (Shift+V or Locate > Vehicles menu)
  - Shows list of all vehicles (672 in Bologna Acosta)
  - Select vehicle, click "Center" to zoom to it
  - Right-click on the now-large vehicle for context menu
- Context menu includes: "Show Current Route" (item ~#5), "Show Parameters" (item ~#15)
- "Show Current Route" highlights the route edges in green

### export_network_statistics Task
- Uses Bologna Pasubio scenario (different from Acosta used by other tasks)
- F9 > Streets tab > coloring dropdown
- Exact option name: "by current occupancy (lanewise, brutto)" (must match exactly)
- After clicking OK: roads turn white (zero occupancy at time 0)
- Start sim with Ctrl+A: occupied roads change color
- Screenshot via scrot

## Common Issues and Solutions

| Issue | Solution |
|-------|----------|
| Simulation runs too fast with `--start` | Don't use `--start`; agent controls playback via Ctrl+A |
| Play button hard to target | Use Ctrl+A keyboard shortcut instead |
| Text field shows truncated value | Verify via clipboard (Ctrl+A, Ctrl+C, then xclip) |
| Can't right-click on vehicles | Use Vehicle Chooser (Shift+V) to center + zoom first |
| Dropdown selection not registering | Reopen dropdown, use pyautogui for precise clicks |
| netedit won't load network | Use `-s network.xml` flag, not positional arg |
| netedit additionals not loading | Use `-a additional.xml` flag |
| "Simulation ended" dialog blocks | Click "No" to keep viewing, or don't run past end time |

## Coordinate Notes (1920x1080 resolution)
- visual_grounding MCP returns coordinates in 1280x720; scale by 1.5x for actual resolution
- Example: VG reports (102, 260) → actual click at (153, 390)

## Timing
- SUMO PPA install: ~60-70s
- Scenario file copy: ~1s
- sumo-gui launch + load: ~5-8s
- netedit launch + load: ~5-8s
- Total task setup (pre_task): ~10s
- Full simulation (Bologna Acosta): ~5655 simulated seconds
