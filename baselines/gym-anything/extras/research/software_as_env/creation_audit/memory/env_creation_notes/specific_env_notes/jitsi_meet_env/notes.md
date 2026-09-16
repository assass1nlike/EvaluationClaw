> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Jitsi Meet Environment — Creation Notes

## Stack
- Docker-in-QEMU: `jitsi/web:stable-9753` + `jitsi/prosody:stable-9753` + `jitsi/jicofo:stable-9753` + `jitsi/jvb:stable-9753`
- Port: 8080 (HTTP, no HTTPS for localhost dev)
- Network: custom Docker bridge `meet.jitsi` with aliases `meet.jitsi` (web) and `xmpp.meet.jitsi` (prosody)
- Config dirs: `/home/ga/.jitsi-meet-cfg/{web,transcripts,prosody/config,prosody/prosody-plugins-custom,jicofo,jvb}`

## Installation (pre_start)
- Package: `docker.io` + `docker-compose-v2` (NOT `docker-compose-plugin` which doesn't exist in Ubuntu 22.04)
- Enable Docker systemd service; add `ga` to `docker` group
- Tools: xdotool, scrot, firefox, epiphany-browser, wmctrl, imagemagick

## Key Docker Compose Configuration Fixes

### 1. Remove `version:` field
- Old `version: '3.5'` causes deprecation warning with Docker Compose v2
- Solution: Remove the `version` field entirely

### 2. BOSH URL Fix (Critical)
- **Problem**: `PUBLIC_URL=http://localhost:8080` with Jitsi's template uses `trimPrefix "https://"` → doesn't strip `http://` → generates `wss://http://localhost:8080/xmpp-websocket` (invalid URL) → "You have been disconnected" error
- **Fix**: Add to web service env:
  ```
  BOSH_RELATIVE=true          # generates /http-bind (relative) instead of absolute URL
  ENABLE_XMPP_WEBSOCKET=0     # disable WebSocket entirely (also generates broken URL)
  ```

### 3. JVB IP Advertisement Fix
- **Problem**: JVB advertises its Docker internal IP (172.18.0.x) to browsers trying to connect
- **Fix**: Add `JVB_ADVERTISE_IPS=127.0.0.1` to jvb service (for browser connecting from localhost)

### 4. Lobby Feature Fix
- **Problem**: Security Options dialog shows no Lobby toggle
- **Fix**: Set `ENABLE_LOBBY=1` in BOTH prosody AND jicofo services (both required, default is 0)

### 5. HTTP Mode
- Add to web service: `DISABLE_HTTPS=1`, `ENABLE_HTTP_REDIRECT=0`, `ENABLE_HSTS=0`

## Firefox (Snap) Key Patterns
- Snap Firefox does NOT support `-profile` flag in setup scripts
- Profile dir: `/home/ga/.mozilla/firefox/jitsi.profile/` (synced to snap profile on first launch)
- Warmup: `DISPLAY=:1 nohup firefox http://localhost:8080 >/tmp/firefox_warmup.log 2>&1 &`
- task_utils.sh restart: use `>/tmp/firefox_task.log` (NOT `/tmp/firefox.log` — root-owned from post_start)
- Lock files to clear: `/home/ga/snap/firefox/common/.mozilla/firefox/jitsi.profile/lock`

## Accessing Security Options
- NOT from shield icon at top (that opens "Performance settings")
- FROM: `(...)` More options button in bottom toolbar → "Security options"
- Once in meeting, toolbar at y~689 in 1280x720 VG scale
- `(...)` button is 2nd from right in toolbar

## join_meeting() Function
The `join_meeting()` in task_utils.sh works by:
1. Clicking the "Enter your name" input at (267, 562) in 1920x1080 to focus it
2. Pressing Enter to submit the pre-join form
3. Waiting 12s for the meeting room to load
4. Moving mouse to center to reveal the toolbar
- **Do NOT click "Join meeting" button by fixed coordinates** — button y-pos varies

## Task Notes
- All 5 setup_task.sh scripts exit successfully (code 0)
- `toggle_lobby` and `share_invite_link` call `join_meeting` to place agent inside active meeting
- `create_meeting` and `change_background` navigate to home page only
- `set_display_name` navigates to /ProductReview pre-join screen (name input visible)
- Permission issue: `/tmp/firefox.log` owned by root from post_start warmup; task_utils uses `/tmp/firefox_task.log`
- Tasks use stub verifiers (`passed: True`) — VLM evaluation external

## Timing
- pre_start: ~60-70s (Docker + packages install)
- post_start: ~120-180s (containers start + Firefox warmup)
- env.reset() from cache with savevm: ~41s
- All 5 tasks sequentially: ~5 min

## Container Verification
```bash
docker ps --format "{{.Names}}: {{.Status}}"
# Should show 4 containers: jitsi-web-1, jitsi-prosody-1, jitsi-jicofo-1, jitsi-jvb-1
curl -sfk http://localhost:8080 | head -5  # Should return Jitsi HTML
```
