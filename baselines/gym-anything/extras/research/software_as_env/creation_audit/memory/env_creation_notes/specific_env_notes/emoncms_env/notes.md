> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Emoncms Environment Notes

**Status**: FULLY VERIFIED 2026-02-23 (all 10 task start states confirmed)

## Stack

Docker Compose with:
- `openenergymonitor/emoncms:latest` — PHP 8.0 / Apache2 / supervisord (`:80`)
- `mariadb:10.11` — database (`emoncms-db`)
- `redis:7.0-alpine` — session/cache (`emoncms-redis`)

Version: Emoncms 11.6.9

Admin credentials: `admin` / `admin`
URL: `http://localhost`

---

## CRITICAL: Settings.ini Env Var Resolution Issue

**Problem**: Emoncms uses `settings.ini` with `{{PLACEHOLDER}}` variables resolved by `resolve_env_vars()` via PHP's `getenv()`. This works fine when supervisord starts Apache (env vars inherited from Docker runtime), but **BREAKS when Apache is restarted** (`service apache2 restart`) because the new Apache process does NOT inherit Docker container env vars.

Symptoms:
```
Error: environment var 'MYSQL_HOST' not defined
Error: environment var 'REDIS_HOST' not defined
...
Fatal error: Redis::connect('{{REDIS_HOST}}', '{{REDIS_PORT}}')
```

**Fix**: In `setup_emoncms.sh`, after the container starts, write `settings.ini` with **hardcoded values** inside the container:

```bash
docker exec emoncms-web bash -c "
cat > /var/www/emoncms/settings.ini << 'EOF'
[sql]
server = db
database = emoncms
username = emoncms
password = emoncms
port = 3306

[redis]
enabled = true
host = redis
port = 6379
prefix = emoncms

[mqtt]
enabled = false
host = localhost
...
EOF
"
```

This makes emoncms work regardless of whether Apache is restarted.

---

## Admin User Creation

**Problem**: Cannot reliably create admin user via web form (`/user/register`) because MQTT env var issues in early versions caused session header problems.

**Fix**: Create admin user directly via MySQL with correct password hash:

```python
import hashlib, secrets
salt = secrets.token_hex(8)         # 16 char salt
apikey_write = secrets.token_hex(16) # 32 char API key (REQUIRED - strlen check)
apikey_read  = secrets.token_hex(16) # 32 char API key

# Emoncms hash: sha256(salt + sha256(password))
inner  = hashlib.sha256(password.encode()).hexdigest()
hashed = hashlib.sha256((salt + inner).encode()).hexdigest()
```

**CRITICAL: API keys must be exactly 32 hex characters!** Emoncms's `user_model.php` checks:
```php
if (strlen($apikey_in)!=32) return array();  // returns empty session
```
Using `secrets.token_hex(8)` = 16 chars FAILS. Use `secrets.token_hex(16)` = 32 chars.

---

## Login Flow (AJAX-based)

Emoncms login is **NOT a traditional form POST**. The login form uses JavaScript/AJAX:
- HTML page: `GET /user/login` — shows the form only
- Login API: `POST /user/login.json` — processes credentials, returns JSON

For curl testing:
```bash
curl -s -c cookie.jar -b cookie.jar \
  "http://localhost/user/login.json" \
  -d "username=admin&password=admin"
# Returns: {"success":true,"message":"Login successful","startingpage":"feed\/list"}
```

For browser (xdotool): The username field has autofocus on `/user/login`. Just type username, Tab, password, Return.

---

## Input Processlist API Bug

`input/process/set` endpoint is unreliable (returns `false`). Use MySQL directly:

```bash
# Set processlist
docker exec emoncms-db mysql -u emoncms -pemoncms emoncms \
  -e "UPDATE input SET processList='1:{feed_id}' WHERE id={input_id};"

# Clear processlist
docker exec emoncms-db mysql -u emoncms -pemoncms emoncms \
  -e "UPDATE input SET processList='' WHERE id={input_id};"
```

Process format: `"1:{feed_id}"` where process 1 = "Log to Feed"

---

## Dashboard Create API

`dashboard/create` returns HTML (not JSON). Use MySQL:

```sql
INSERT INTO dashboard (userid, name, alias, description, main, public)
VALUES (1, 'Energy Overview', 'energy_overview', '...', 0, 0);
```

---

## URL Reference

| Page | URL | Returns |
|------|-----|---------|
| Login | `/user/login` | HTML |
| Login API | `/user/login.json` | JSON |
| Feeds list | `/feed/list` | HTML |
| Inputs view | `/input/view` | HTML ✓ |
| Inputs API | `/input/list` | JSON (NOT HTML) |
| Input API Helper | `/input/api` | HTML |
| Dashboard list | `/dashboard/list` | HTML |
| Dashboard edit | `/dashboard/edit?id=N` | HTML |
| Graph | `/graph` | HTML |
| Admin users | `/admin/users` | HTML ✓ |
| User admin (wrong) | `/user/admin` | Blank content |

**Key distinction**: `/input/list` = JSON API endpoint. `/input/view` = HTML UI page.
**Key distinction**: `/user/admin` = blank page. `/admin/users` = user management page with "+ Add new user".

---

## Seed Data

Six feeds created for admin (userid=1):
1. House Power (tag: power, unit: W, engine: PHPFina, interval: 10s)
2. Appliances (tag: power, unit: W, engine: PHPFina, interval: 10s)
3. Solar PV (tag: solar, unit: W, engine: PHPFina, interval: 10s)
4. House Temperature (tag: temperature, unit: degC, engine: PHPFina, interval: 60s)
5. Heat Pump Power (tag: heat, unit: W, engine: PHPFina, interval: 10s)
6. Test Feed (tag: test, unit: W, engine: PHPFina, interval: 10s)

Inputs (node "home"): power1, power2, solar, temp, heatpump
Inputs (node "sensor"): temp

30 days × 24 hours of historical hourly data for feeds 1-5.

Dashboard: "Energy Overview" (id=1)

---

## 10 Tasks

| Task | Start URL | Key Setup |
|------|-----------|-----------|
| create_feed | `/feed/list` | No setup needed |
| add_input_process | `/input/view` | Clear heatpump processlist via MySQL |
| create_dashboard | `/dashboard/list` | No setup needed |
| add_realtime_widget | `/dashboard/edit?id=1` | Energy Overview dashboard must exist |
| rename_feed | `/feed/list` | No setup needed |
| delete_feed | `/feed/list` | Ensure Test Feed exists |
| view_feed_graph | `/graph` | No setup needed |
| configure_feed_interval | `/feed/list` | Reset House Temperature interval to 10s |
| create_user | `/admin/users` | Remove john_doe if exists |
| post_input_data | `/input/api` | No setup needed |

---

## Supervisord Architecture

The emoncms Docker image uses `supervisord` as PID 1 (not a shell entrypoint):
```
CMD: /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
Programs: apache, emoncms_mqtt
```

Apache runs as `apache2-foreground` under supervisord. Supervisord correctly passes Docker env vars to Apache, but `service apache2 restart` breaks this inheritance.

---

## Docker Network Hostnames

Inside the emoncms-web container, hostname resolution works:
- `db` → MariaDB container IP
- `redis` → Redis container IP
- `localhost` → 127.0.0.1 (for MQTT disabled)

---

## Testing Commands

```bash
# Check feeds
curl -s "http://localhost/feed/list.json?apikey=APIKEY"

# Check inputs
curl -s "http://localhost/input/list.json?apikey=APIKEY"

# Test login
curl -s -c /tmp/c.jar -b /tmp/c.jar "http://localhost/user/login.json" \
  -d "username=admin&password=admin"

# Post input data
curl -s "http://localhost/input/post.json?apikey=APIKEY&node=home&fulljson=%7B%22power1%22%3A1850%7D"
```
