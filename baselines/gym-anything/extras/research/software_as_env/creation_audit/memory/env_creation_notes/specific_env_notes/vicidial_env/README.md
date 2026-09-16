> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Vicidial Env Notes

## Overview

- Environment: `benchmarks/cua_world/environments/vicidial_env`
- Runner: QEMU (`runner: qemu`)
- App: Vicidial (web UI) running inside Docker within the VM
- Browser: Firefox

## Docker Image

- Image: `sairajdockerimageshub/vicidial` (pinned digest in `benchmarks/cua_world/environments/vicidial_env/config/docker-compose.yml`)
- Expected admin credentials: `6666 / andromeda` (image default, not secret)
- Admin URL: `http://localhost/vicidial/admin.php`
- This image uses Apache HTTP Basic Auth in front of the Vicidial admin UI; the browser may show a native sign-in dialog. Use the same credentials (`6666` / `andromeda`).

## Key URLs (Admin UI)

- Admin dashboard: `http://localhost/vicidial/admin.php`
- Lists listing: `http://localhost/vicidial/admin.php?ADD=100`
- Add a new list: `http://localhost/vicidial/admin.php?ADD=111`
- List Loader (4th gen): `http://localhost/vicidial/admin_listloader_fourth_gen.php`

## Database Access (Inside Container)

The Docker image includes MySQL. DB credentials are present in `/etc/astguiclient.conf`
inside the container.

Convenient host-side command pattern (run inside the VM):

```bash
sudo docker exec vicidial mysql -ucron -p1234 -D asterisk -N -e "SELECT COUNT(*) FROM vicidial_users;"
```

## Permission Quirk (Important)

The default admin user `6666` may have a high `user_level` but can still be blocked
from list/lead pages unless these flags are enabled:

```sql
UPDATE vicidial_users
SET modify_lists='1', modify_leads='1', modify_campaigns='1', view_reports='1'
WHERE user='6666';
```

Without this, `admin.php?ADD=111` can show a "You do not have permission" message.

## Real Data

The environment includes a real-world leads CSV derived from U.S. Senate public contact info:

- `benchmarks/cua_world/environments/vicidial_env/assets/us_senators_vicidial_leads_2026-02-14.csv`
- `benchmarks/cua_world/environments/vicidial_env/assets/us_senators_vicidial_standard_format_list9001_2026-02-14.csv`

This file is copied into the VM at:

- `/home/ga/Documents/VicidialData/us_senators_vicidial_leads_2026-02-14.csv`
- `/home/ga/Documents/VicidialData/us_senators_vicidial_standard_format_list9001_2026-02-14.csv`
