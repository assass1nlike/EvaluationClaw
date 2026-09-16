> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Rocket.Chat Env Notes

## Architecture
- Docker-in-QEMU pattern: `ubuntu-gnome-systemd_highres` base VM
- 3 Docker containers: `rc-rocketchat` (Rocket.Chat 8.1.0), `rc-mongodb` (MongoDB Community 8.2), `rc-nats` (NATS 2.11)
- Port: Rocket.Chat on port 3000 inside the VM
- Browser: Epiphany (GNOME Web) preferred, Firefox as fallback
- Runner is explicitly `qemu` to match host constraints (no direct Docker daemon on host)

## Credentials
- Admin: `admin` / `Admin1234!`
- Agent user: `agent.user` / `AgentPass123!`

## Real Data Source
- `benchmarks/cua_world/environments/rocket_chat_env/assets/rocketchat_releases_github_api_2026-02-16.json`
- Source: `https://api.github.com/repos/RocketChat/Rocket.Chat/releases?per_page=25`
- 12 release announcements seeded into `#release-updates` channel
- Releases span from 7.8.5 to 8.1.0 (Dec 2025 - Feb 2026)

## Setup Wizard Bypass
- Environment variables on the rocketchat container:
  - `ADMIN_USERNAME`, `ADMIN_PASS`, `ADMIN_EMAIL` for auto admin creation
  - `OVERWRITE_SETTING_Show_Setup_Wizard=completed` to skip wizard
  - `OVERWRITE_SETTING_Accounts_AllowUserRegistration=false` to prevent unwanted registration
- **CRITICAL**: The `OVERWRITE_SETTING_Show_Setup_Wizard=completed` env var does NOT reliably prevent the wizard from appearing on first admin login. The `setup_rocket_chat.sh` post_start hook must ALSO set `Show_Setup_Wizard=completed` and `Organization_Type=community` via the REST API after seeding. Without this, first admin login redirects to `/setup-wizard/2` (Organization Info step). This fix was discovered and applied during interactive testing.

## MongoDB Replica Set
- MongoDB requires replica set (`rs0`) for Rocket.Chat's oplog-based reactivity
- Replica set initialization is done in `setup_rocket_chat.sh` after container startup
- Must wait for PRIMARY state before Rocket.Chat can connect

## Deterministic Start-State Strategy
- `post_start` seeds channel `#release-updates` with 12 real release announcements and writes `/tmp/rocket_chat_seed_manifest.json`
- `pre_task` restarts the browser deterministically and lands on Rocket.Chat login page
- Each task's `setup_task.sh` cleans up its target state via API before presenting login page

## Browser Quirks
- `task_utils.sh` supports both Epiphany and Firefox
- Epiphany is preferred (faster startup, no snap issues)
- Firefox snap on Ubuntu: no `-profile` flag supported
- `restart_firefox()` has retry logic (up to 4 attempts) with "Close Firefox" dialog handling

## Timing
- Full boot (no cache): ~2.5 min (pre_start: ~90s, post_start: ~25s, pre_task: ~16s)
- With pre_start cache: ~2 min
- Rocket.Chat HTTP readiness: ~25s after container start

## UI Coordinates (1280x720 scale, multiply by 1.5 for 1920x1080)
- Login page username field: (855, 337)
- Login page password field: (855, 400)
- Login page Login button: (717, 462)
- "Set Web as default?" No button: (1208, 58)
- #release-updates sidebar: (120, 146)
- "Add topic" link in channel header: (417, 124)
- Channel Info "Edit" button: (1125, 433)
- Edit channel Save button: (1179, 693)

## Known Operational Considerations
- Disk quota can be exceeded when creating savevm checkpoints (6.5GB RAM snapshot)
- The "Set Web as your default browser?" banner appears in Epiphany but doesn't block interaction
- URL bar shows `http://localhost:3000/home` instead of `/login` after redirect
- Docker pull auth is optional and supported via mounted env file (`/workspace/config/dockerhub.env`)
- Rocket.Chat link previews render automatically for GitHub URLs, which adds visual clutter to messages
- Channel topic editing: click "Add topic" → Channel Info panel → Edit → fill Topic field → Save
- React to message: hover over message → emoji icon → pick reaction (or use `:thumbsup:` in message box)

## 10 Tasks

| Task | Difficulty | Description |
|------|-----------|-------------|
| post_release_followup | easy | Post a specific follow-up message in #release-updates |
| create_private_channel | medium | Create a private channel "security-incidents" with agent.user |
| pin_release_message | medium | Pin the 8.0.0 release message in #release-updates |
| send_direct_message | easy | Send a DM to agent.user with specific text |
| search_release_keyword | hard | Search for "7.8.5", find the message, reply in a thread |
| invite_user_to_channel | medium | Create "deployment-log" channel and invite agent.user |
| star_release_message | medium | Star the 7.10.7 release message |
| set_channel_topic | easy | Set a specific topic on #release-updates |
| react_to_message | medium | Add thumbsup emoji to the 8.1.0 release message |
| change_user_status | easy | Change status to "Busy" with custom status text |
