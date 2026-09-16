> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Snipe-IT Environment Creation Notes

## Overview

Snipe-IT is an open-source IT asset management system built on PHP/Laravel. The environment runs Snipe-IT via Docker-in-QEMU using `snipe/snipe-it:latest` and `mariadb:10.11` containers.

## Architecture

```
QEMU VM (ubuntu-gnome-systemd_highres, 8GB RAM)
├── Docker
│   ├── snipeit-app (snipe/snipe-it:latest) → port 8000
│   └── snipeit-db (mariadb:10.11) → port 3306 (internal)
├── Firefox (snap) → http://localhost:8000
└── SSH (port 22) → forwarded to host
```

## Installation Quirks

### Docker Compose v1 vs v2
- Ubuntu 22.04 ships `docker-compose` v1 (1.29.2, Python-based) via apt
- v1 is incompatible with newer Docker images (`KeyError: 'ContainerConfig'`)
- **Solution**: Install Docker Compose v2 as a plugin:
  ```bash
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -SL "https://github.com/docker/compose/releases/download/v2.24.5/docker-compose-linux-x86_64" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  ```
- Use `docker compose` (space, not hyphen) in all commands
- **Gotcha**: The docker-compose.yml filename keeps the hyphen — don't let global find-and-replace change it

### Firefox Snap Compatibility
- Ubuntu 22.04 ships Firefox as a snap package
- Snap Firefox **cannot** use `-profile /path/to/profile` for paths outside its sandbox
- Attempting to use `-profile` causes Firefox to hang with a "Close Firefox" dialog
- **Solution**:
  1. Launch Firefox `--headless` once to create the default profile
  2. Find the snap profile dir: `~/snap/firefox/common/.mozilla/firefox/*.default*`
  3. Inject `user.js` preferences into that default profile
  4. Launch Firefox without `-profile` flag: `firefox http://localhost:8000/login`

### VNC Password Bug
- `VNCSpec.password` defaults to `None` in the framework's `specs.py`
- The runner code checks `vnc_cfg.password if vnc_cfg else "password"` — since VNCSpec() is truthy, it uses `None`
- **Solution**: Always add `"vnc": {"password": "password"}` to env.json

## Snipe-IT Setup Wizard Bypass

Snipe-IT has a first-run setup wizard that blocks API access. Bypass it by inserting a settings row directly:

```sql
INSERT INTO settings (id, created_at, updated_at, site_name, auto_increment_assets, auto_increment_prefix, per_page)
VALUES (1, NOW(), NOW(), 'Snipe-IT Asset Management', 1, 'ASSET-', 20)
ON DUPLICATE KEY UPDATE site_name='Snipe-IT Asset Management';
```

## OAuth / API Token Generation

### OAuth Keys
- Snipe-IT container runs Apache as user `docker` (uid=10000, gid=50/staff), not `www-data`
- OAuth keys symlink from `storage/oauth-*.key` → `/var/lib/snipeit/keys/`
- Keys must be readable by the `docker` user: `chmod 644`, `chown 10000:50`
- `passport:keys` command may not write to the correct symlink target — generate with openssl directly:
  ```bash
  docker exec snipeit-app bash -c '
      openssl genrsa -out /var/lib/snipeit/keys/oauth-private.key 4096 2>/dev/null
      openssl rsa -in /var/lib/snipeit/keys/oauth-private.key -pubout -out /var/lib/snipeit/keys/oauth-public.key 2>/dev/null
      chmod 644 /var/lib/snipeit/keys/oauth-private.key /var/lib/snipeit/keys/oauth-public.key
      chown 10000:50 /var/lib/snipeit/keys/oauth-private.key /var/lib/snipeit/keys/oauth-public.key
  '
  ```

### API Token
- Use a PHP script with `docker cp` to generate a personal access token:
  ```php
  <?php
  require '/var/www/html/vendor/autoload.php';
  $app = require_once '/var/www/html/bootstrap/app.php';
  $app->make('Illuminate\Contracts\Console\Kernel')->bootstrap();
  $user = App\Models\User::where('username', 'admin')->first();
  $token = $user->createToken('seed-token');
  echo $token->accessToken;
  ```

## Data Seeding

### Dynamic ID Capture
All entity creation uses the API with dynamic ID capture via a `get_id()` helper:
```bash
get_id() {
    echo "$1" | jq -r '.payload.id // .id // empty' 2>/dev/null
}
```
This avoids hardcoding IDs which can change between fresh installs.

### Data Counts
| Entity | Count | Notes |
|--------|-------|-------|
| Status Labels | 4 custom + 3 built-in = 7 | Pending, Ready to Deploy, Archived are built-in |
| Categories | 15 custom + 1 built-in = 16 | Misc Software is built-in |
| Manufacturers | 8 | Dell, HP, Lenovo, Apple, Cisco, Samsung, Microsoft, Logitech |
| Locations | 6 | SF HQ A/B, NYC, Austin, London, Remote |
| Departments | 7 | IT, Engineering, HR, Finance, Marketing, Sales, Operations |
| Suppliers | 3 | CDW, Insight Direct, SHI International |
| Models | 11 | Laptops, desktops, monitors, networking, servers |
| Users | 10 + 1 admin = 11 | Across departments and locations |
| Hardware | 20 (19 visible) | 1 is archived/retired |
| Checkouts | 5 | Assigned to various employees |
| Licenses | 3 | M365, Adobe CC, Windows 11 Enterprise |
| Accessories | 3 | Mouse, adapter, headset |
| Consumables | 1 | Toner |
| Components | 2 | RAM, SSD |

### API Quirks
- Default API listing returns only first page; `licenses` endpoint shows 1 but all 3 exist
- Archived assets not shown in default hardware listing (19 visible out of 20 total)
- The "Licenses" card on the dashboard shows total seat count (160), not license count (3)

## Service Timing

| Phase | Typical Duration |
|-------|-----------------|
| VM boot | ~20s |
| pre_start (install) | ~60s |
| post_start (Docker pull + setup) | ~90s |
| pre_task (task setup) | ~5s |
| **Total** | ~3 minutes |

## Task Design

### create_asset Task
- **Goal**: Create ASSET-L011 (HP EliteBook 860 G11 - Marketing)
- **Start state**: Dashboard with all data visible, "Create New" button accessible
- **pre_task**: Records initial asset count and max ID for verification

### checkout_asset Task
- **Goal**: Check out ASSET-L002 to Michael Thompson
- **Start state**: Dashboard with navigation to hardware list
- **pre_task**: Verifies ASSET-L002 exists, is not checked out, records initial state
- **Key detail**: If asset was previously checked out, pre_task checks it back in

## Common Issues

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| VM hangs during boot | VNC password set to "None" | Add `"vnc": {"password": "password"}` to env.json |
| `KeyError: 'ContainerConfig'` | Docker Compose v1 incompatibility | Install Compose v2 plugin |
| Firefox shows "Close Firefox" dialog | Snap can't use `-profile` flag | Use default profile, inject user.js |
| `runner.exec()` returns int | It returns exit code, not output | Use SSH subprocess for output capture |
| OAuth 401 errors | Keys not readable by Apache user | `chmod 644`, `chown 10000:50` on key files |
