> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Mattermost Environment Notes

## Installation

- **Mattermost Team Edition 10.4** via Docker Compose
- **PostgreSQL 15 Alpine** as database
- Docker-in-QEMU pattern (docker.io + docker-compose v1 from Ubuntu repos)
- `docker-compose-plugin` (v2) is NOT available in Ubuntu 22.04 default repos; use `docker-compose` (v1) instead
- Docker Compose v1 command: `docker-compose`, Docker Compose v2 command: `docker compose`

## Browser

- **Snap Firefox does NOT work** when launched via SSH/su in the QEMU VM. The snap cgroup error prevents it from starting.
- **Solution**: Install `epiphany-browser` (GNOME Web) and use it as the primary browser
- Window detection: grep for `epiphany|web|firefox|mozilla|mattermost`

## Mattermost API (v4)

- Login: `POST /api/v4/users/login` with `{"login_id": "...", "password": "..."}`
  - Returns auth token in the `Token` response header (NOT in JSON body)
- System ping: `GET /api/v4/system/ping` - returns 200 when ready
- Create user: `POST /api/v4/users`
- Create team: `POST /api/v4/teams`
- Create channel: `POST /api/v4/channels`
- Post message: `POST /api/v4/posts`
- Pin post: `POST /api/v4/posts/{post_id}/pin`
- Get pinned posts: `GET /api/v4/channels/{channel_id}/pinned`
- Update channel: `PUT /api/v4/channels/{channel_id}`

## First User Setup

- The first user created on a fresh Mattermost install automatically becomes system admin
- No setup wizard to bypass (unlike Rocket.Chat)
- Set `MM_SERVICESETTINGS_ENABLEONBOARDINGFLOW: "false"` to skip onboarding

## Data Seeding

- 27 real Mattermost releases fetched from GitHub API
- 15 selected for seeding into the `release-updates` channel
- Additional channels: engineering, devops, general-discussion (with realistic messages)
- Seed manifest saved to `/tmp/mattermost_seed_manifest.json`

## Service Timing

- PostgreSQL ready: ~5-10 seconds after container start
- Mattermost HTTP ready: ~10-15 seconds after container start (fast!)
- Total env setup time: ~100-120 seconds (including Docker image pulls from cache)

## Task Setup Patterns

- Use `mm_get_auth_token` from task_utils.sh to authenticate
- Channel switcher: `Ctrl+K` in Mattermost UI
- All tasks start at the login page; agent must log in first
- Clean state ensured by each task's setup_task.sh (unpin messages, delete channels, clear headers)

## Credentials

- Admin: `admin` / `Admin1234!`
- Agent: `agent.user` / `AgentPass123!`
- Team: `main-team` (display: "Main Team")
- Mattermost URL: `http://localhost:8065`

## Known Issues

- Email notifications warning banner shows at top of Mattermost UI ("Email notifications have not been configured")
- "Set Web as your default browser?" notification from Epiphany on first launch
- Both are cosmetic and don't affect functionality

## Gotchas Discovered During Testing

### Mattermost API error responses have `id` field
- When looking up a user by username via `GET /api/v4/users/username/{name}`, a 404 response returns JSON like `{"id": "app.user.get_by_username.app_error", ...}`
- The `id` field contains the error code, NOT a user ID
- Always check the HTTP status code (200 = exists, 404 = not found) rather than parsing the response body `.id` field
- Example fix: use `curl -sS -o /tmp/check.json -w "%{http_code}"` and check status code before parsing

### xdotool and Epiphany browser
- `xdotool type/click` without `--window <wid>` does not reliably target Epiphany input fields
- Always use `xdotool search --name Mattermost` to get the window ID, then pass `--window <wid>` to all xdotool commands
- Use `Tab` key to move between form fields (clicking on password field directly may not work)
- Login flow: click username field -> type username -> Tab -> type password -> Enter

### Docker Compose v1 vs v2
- Ubuntu 22.04 repos have `docker-compose` v1 (1.29.2) but not `docker-compose-plugin` (v2)
- The setup script uses `choose_compose_cmd()` to auto-detect which is available
- Both v1 and v2 work for this environment's simple compose file
