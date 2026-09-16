> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Ardour DAW Environment Notes

## Installation Quirks

- **Binary name**: On Ubuntu 22.04, `apt install ardour` provides Ardour 6.9. The binary is `/usr/bin/ardour` (a shell script wrapper), actual binary at `/usr/lib/ardour6/ardour-6.9.0~ds0`.
- **CLI tools**: `ardour6-new_session -s <sample_rate> <path> <name>` creates sessions without GUI. The `-s 44100` flag sets sample rate; the last argument is the session name.
- **Audio backends**: ALSA, JACK, Dummy ("None (Dummy)"), PulseAudio. The Dummy backend works without hardware.
- **`hide-dummy-backend`**: Default config hides the Dummy backend. Must be set to `0` in `~/.config/ardour6/config`.

## First-Run Wizard

Ardour shows a multi-page wizard on first launch. Completion creates a `.a6` marker file in `~/.config/ardour6/`. The wizard Forward button is at approximately (805, 492) in 1280x720 scale. Clicking Forward 10 times completes all pages.

## Audio Engine Configuration

The critical discovery: audio engine state must be in `<Extra><AudioMIDISetup><EngineStates>` section, not at the root level. The exact format for Dummy backend:

```xml
<Extra>
  <AudioMIDISetup>
    <EngineStates>
      <State backend="None (Dummy)" driver="Normal Speed" device="Silence"
             input-device="" output-device="" sample-rate="44100" buffer-size="1024"
             n-periods="0" input-latency="0" output-latency="0"
             input-channels="0" output-channels="0" lm-input="" lm-output=""
             active="1" use-buffered-io="0" midi-option="1 in, 1 out, Silence" lru="1">
        <MIDIDevices/>
      </State>
    </EngineStates>
  </AudioMIDISetup>
</Extra>
```

With `try-autostart-engine=1` and this EngineStates, subsequent launches skip the Audio/MIDI Setup dialog entirely.

## Critical Bug: pkill -f Self-Kill

`pkill -f "ardour"` matches the full command line of all processes. Since the setup script is named `setup_ardour.sh`, running `pkill -f "ardour"` kills the script itself. Fix: use `pkill -f "/usr/lib/ardour"` to only match the actual Ardour binary path.

## Session Management

- Sessions are stored as XML `.ardour` files
- New sessions have only a Master bus; audio tracks must be added explicitly
- `Ctrl+Shift+N` opens the Add Track/Bus/VCA dialog
- `Ctrl+S` saves, `Ctrl+Q` quits (does NOT auto-save)
- Track names are stored in Route elements: `<Route name="Audio 1" ...>`

## Audio Data

Real public domain audio is downloaded from Wikimedia Commons:
- Primary: Beethoven Moonlight Sonata (MP3 → WAV via ffmpeg)
- Stored at `/home/ga/Audio/samples/moonlight_sonata.wav` (~5.3MB)
- Copied to `/home/ga/Audio/import_me.wav` for task use

## UI Automation Tips

- Dialog positions vary between launches; always use `xdotool getwindowgeometry` for window-relative coordinates
- `wmctrl -a "title"` focuses windows by title, `wmctrl -r "title" -b add,maximized_vert,maximized_horz` maximizes
- `setsid` must come AFTER environment variables: `DISPLAY=:1 setsid ardour` (not `setsid DISPLAY=:1 ardour`)
- Ardour uses GTK2 widgets; combo boxes require clicking on the dropdown arrow area specifically

## Verification Gotchas

- Stub verifiers return `passed: True` always; real verification requires external VLM evaluators
- The `rename_track` task checks for track name in session XML (sed-based), not via visual inspection
- The `export_session` task checks for WAV files in `/home/ga/Audio/export/`
