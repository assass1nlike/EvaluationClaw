> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Nx Witness VMS Environment Notes

## Overview
- Application: Nx Witness VMS (Network Optix Video Management System) 5.1.5.39242
- OS: Ubuntu (QEMU VM)
- Interface: Web Admin at `https://localhost:7001/static/index.html` (HTTPS, self-signed cert)
- Admin credentials: `admin` / `Admin1234!`
- SSH user: `ga` / `password123`
- Resolution: 1920x1080

## Installation
- Package: `nxwitness-mediaserver_5.1.5.39242_linux_arm64.deb` (or x64)
- Download from Network Optix trial/developer portal
- Install: `dpkg -i nxwitness-mediaserver*.deb && apt-get install -f -y`
- Service: `networkoptix-mediaserver` (systemd)
- Desktop client also installed: `/opt/networkoptix/client/5.1.5.39242/bin/client` (shell script)
- Client launcher: `/opt/networkoptix/client/5.1.5.39242/bin/applauncher`

## Initialization (CRITICAL)
- On first run, server starts with default admin/admin and NULL system ID
- **MUST call `POST /rest/v1/system/setup` to initialize atomically**
- Correct format:
  ```json
  {
    "name": "GymAnythingVMS",
    "settingsPreset": "security",
    "settings": {},
    "local": {"password": "Admin1234!"}
  }
  ```
- `settingsPreset="security"` sets `trafficEncryptionForced=true`
- This endpoint only accepts calls when `localSystemId` is the NULL UUID
- Get Bearer token first with default admin/admin credentials

## API Versions
- **ONLY v1 and v2 are supported** — NOT v3
- All API calls use `/rest/v1/` prefix
- Authentication: `POST /rest/v1/login/sessions` → Bearer token
- Token format: `vms-{uuid}-{random}` (e.g., `vms-db2d59c4412c32afbb0e6536bc221196-het8jXYKyd`)
- Tokens expire after ~8 hours (session duration limit)

## Auth Mechanism for Web Admin
- REST login: `POST /rest/v1/login/sessions` → JSON `{"token": "..."}`
- Cookie auth (for web admin UI): GET `/rest/v1/login/sessions/{token}?setCookie=true` → sets `x-runtime-guid` cookie
- `/api/` endpoints need BOTH the cookie AND `X-Runtime-Guid` header
- Web admin itself handles auth transparently after browser login

## Web Admin Structure (5.x)
- URL: `https://localhost:7001/static/index.html#/...`
- Top navigation: **View**, **Settings**, **Information**, **Monitoring**
- **View**: Live camera stream viewer (left sidebar: server name, cameras)
- **Settings** (`#/settings`): System Administration
  - **General**: System name (editable with pencil icon), Merge System, Nx Cloud, System Settings, Security
  - **Licenses**: License management
  - **Cameras** (`#/settings/cameras`): List cameras, select for detail
    - Camera detail: Image (Aspect Ratio, Rotation), Audio (Enable Audio), Authentication (Edit Credentials), Motion Detection Sensitivity
    - **NO recording schedule section** — recording is desktop-client-only in 5.x
    - **NO Add Camera button** — cameras are discovered/added via desktop client
  - **Users** (`#/settings/users`): List users, click to view/edit
    - User detail: Name, Email, Change Password, Role shown
    - **Add User button**: `+` button appears on hover over "Users" section header (CSS hover, hard to capture in screenshots); confirmed in JS source (`AddUserModalContent` lazy-loaded from "common" chunk)
    - **Role options**: Live Viewer, Viewer, Advanced Viewer, Administrator, Owner (confirmed from main.js source analysis)
    - **"Custom" role**: Means `permissions=NONE`/`NoPermission` — NOT a selectable role, just displayed when user has no standard role
  - **Servers**: Server details
- **Information** (`#/health`): Health/Alerts panel, System/Servers/Cameras/Storage/Network sections
- **Monitoring** (`#/monitoring`): CPU/RAM/Network graphs and Logs

## Key Web Admin Coordinates (1920x1080)
- Sidebar "Cameras": VG(103, 248) → actual(154, 372)
- Sidebar "Users": VG(96, 275) → actual(144, 412)
- Sidebar "Servers": VG(100, 302) → actual(150, 453)
- System name edit icon: VG(452, 168) → actual(678, 252)
- Camera "Edit Credentials" button: VG(349, 535) → actual(523, 802)
- Camera "Enable Audio" checkbox: VG(316, 467) → actual(474, 700)
- Camera "Rotation" dropdown: VG(440, 400) → actual(660, 600)

## Web Admin Login (Firefox)
- Navigate to `https://localhost:7001/static/index.html`
- Accept SSL warning: Advanced → Accept the Risk and Continue
  - "Advanced..." button: VG(879, 470) → actual(1319, 705)
  - "Accept the Risk and Continue": VG(835, 671) → actual(1253, 1007)
- Login form: click username, type admin, Tab to password, type password, Escape (dismiss FF pwd mgr), Enter
- "Save password?" Not Now button: VG(462, 222) → actual(693, 333)
- After login: shows Settings/General page with sidebar navigation

## Virtual Cameras (testcamera)
- Binary: `/opt/networkoptix/mediaserver/bin/testcamera`
- Usage: `testcamera --local-interface=<server_ip> "files=/path/video.mp4;count=3"`
- Creates N cameras using RTSP auto-discovery on LAN
- Cameras appear as model "TestCameraLive", vendor "NetworkOptix"
- Camera status: "Online" (live streaming from video file in loop)
- **CRITICAL**: Must specify `--local-interface` or cameras won't be discovered

## System Name Change
- API: `PATCH /rest/v1/system/settings` with `{"systemName": "NewName"}`
- **NOT PUT** — PUT returns "Unknown OpenAPI schema method PUT for /rest/v1/system/settings"
- Web admin shows system name at top of General settings with pencil edit icon
- Field: `systemName` (not `name` — that's in `/rest/v1/system/info`)

## Desktop Client (applauncher)
- Binary: `/opt/networkoptix/client/5.1.5.39242/bin/applauncher`
- Launch: `DISPLAY=:1 /opt/networkoptix/client/5.1.5.39242/bin/applauncher &`
- First-run dialogs (handled in warm-up):
  1. GNOME Keyring: "Choose password for new keyring" — click Continue (VG 707,452 → actual 1060,678)
  2. GNOME Keyring: "Store passwords unencrypted?" — click Continue (VG 707,419 → actual 1060,628)
  3. EULA: "I Agree" button (VG 885,522 → actual 1327,783)
- After dialogs: welcome screen shows "GymAnythingVMS" tile with localhost
- Connect by clicking the tile → enter admin/Admin1234! if prompted
- **IMPORTANT**: These dialogs only appear on first run — must be handled in post_start warm-up

## Data Seeded
- **System**: GymAnythingVMS
- **Cameras** (3): Parking Lot Camera, Entrance Camera, Server Room Camera (all TestCameraLive, Online)
- **Users** (6):
  - admin (Owner)
  - security.operator / Operator2024!
  - camera.admin / CamAdmin2024!
  - site.manager / Manager2024!
  - john.smith / JohnSmith2024!
  - sarah.jones / SarahJones2024!

## Tasks (5)
1. **add_camera** → Edit Entrance Camera credentials (username: camuser, password: Cam@SecurePass2024)
   - Start: Cameras section open, Entrance Camera selected
2. **configure_recording** → Set Parking Lot Camera Rotation=90°, Enable Audio
   - Start: Cameras section open, Parking Lot Camera needs selection
3. **create_user** → Create user mike.chen (Mike Chen), email, Viewer role
   - Start: Settings → Users section with 6 existing users
4. **create_layout** → Create "Security Overview" layout in desktop client (all 3 cameras)
   - Start: Desktop client open, welcome screen showing GymAnythingVMS tile
5. **rename_system** → Rename system from "GymAnythingVMS" to "SecurityCentralVMS"
   - Start: Settings → General page with system name and edit icon visible

## Common Errors & Fixes
- `POST /rest/v3/...` → **v3 not supported**, use `/rest/v1/`
- `POST /rest/v1/system/setup` returns "Setup is only allowed for new System" → already initialized
- `PATCH /rest/v1/devices/{id}` with `schedule` field works but recording requires desktop client to view
- `su - ga -c "..."` fails from non-root SSH session → run commands directly as ga user
- Desktop client shows "Offline" → server not running or wrong port
- API returns 401 → token expired, call `POST /rest/v1/login/sessions` to refresh
- testcamera not discovered → must use `--local-interface=<server_ip>`, NOT localhost

## SQLite Database
- Path: `/opt/networkoptix/mediaserver/var/ecs.sqlite`
- Table `vms_userprofile` has `digest` column (BLOB, stores HTTP auth digest)
- `settingsPreset="security"` sets digest to `http_is_disabled` string
- After setup: PATCH to `/rest/v1/users/admin` recomputes digest from new password
- DB is only for reference — API is the correct way to interact
