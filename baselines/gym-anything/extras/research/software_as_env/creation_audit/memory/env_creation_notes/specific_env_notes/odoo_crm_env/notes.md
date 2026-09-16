> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Odoo CRM Environment Notes

## Architecture

- Docker-in-QEMU: `odoo:17.0` + `postgres:15`, port 8069
- Admin: `admin` / `admin`
- DB name: `odoodb`
- Docker container names: `odoo-web`, `odoo-db`
- Docker Compose v2 (`docker compose`) in `/home/ga/odoo/`

## Installation (pre_start: install_odoo.sh)

```bash
apt-get install -y docker.io
apt-get install -y docker-compose-plugin  # v2
apt-get install -y firefox wmctrl xdotool x11-utils xclip curl jq python3-pip scrot imagemagick
```

## Setup (post_start: setup_odoo.sh)

1. Start PostgreSQL: `docker compose up -d db` + poll `pg_isready`
2. Initialize Odoo DB with CRM modules:
   ```bash
   docker compose run --rm web odoo --stop-after-init -d odoodb -i crm,contacts,mail
   ```
   This loads demo data (44 CRM records).
3. Start Odoo web: `docker compose up -d web` + poll HTTP 200
4. Seed task-specific records via `python3 /workspace/data/seed_crm.py`
5. Firefox snap warm-up:
   - `su - ga -c "DISPLAY=:1 firefox --headless &"` (headless creates default profile)
   - Wait 10s, kill
   - Find `.default*` profile via `find ... -name '*.default*' -type d`
   - Inject clean `user.js` (no e10s/WebRender overrides!)
   - Warm-up login: `su - ga -c "DISPLAY=:1 firefox URL &"` (NO -profile flag)

## Critical Firefox Notes

**ISSUE**: Firefox snap on Ubuntu 22.04 with QEMU renders blank pages with custom user.js settings that disable e10s or WebRender. Blank content area = rendering is broken.

**SOLUTION**: Use the Vtiger pattern exactly:
1. Headless warm-up to create auto-generated `.default*` profile
2. Find that profile (path like `/home/ga/snap/firefox/common/.mozilla/firefox/f78vxr87.default`)
3. Inject CLEAN user.js (only first-run suppression prefs, NO `dom.ipc.processCount=1`, NO `browser.tabs.remote.autostart=false`)
4. Launch Firefox WITHOUT `-profile` flag

**DO NOT**:
- Create custom profiles.ini pointing to custom directory
- Use `-profile` flag with Firefox snap
- Disable e10s (`browser.tabs.remote.autostart=false`)
- Disable WebRender (`gfx.webrender.enabled=false`)
- Use `--no-sandbox` (not a valid Firefox flag, crashes Firefox)

## URL Notes

- `/odoo/crm` → HTTP 404 (Odoo Community 17 — route not exposed)
- `/odoo/contacts` → HTTP 404 (same issue)
- Hash URLs work correctly:
  - CRM Pipeline: `http://localhost:8069/web#action=209&cids=1&menu_id=139`
  - Contacts: `http://localhost:8069/web#action=154&cids=1&menu_id=117`
  - CRM form: `http://localhost:8069/web#action=209&id={ID}&model=crm.lead&view_type=form&cids=1&menu_id=139`

**Action/Menu IDs for this installation:**
- CRM Pipeline action: 209, CRM root menu: 139
- Contacts action: 154, Contacts root menu: 117
- New Lead action: 211
- New Opportunity action: 223

## Login Coordinates (1920x1080)

- Email field: actual(993, 422)  — VG(662, 281)
- Password field: actual(993, 503) — VG(662, 335)
- "Log in" button: actual(993, 569) — VG(662, 379)
- Note: VG scale is 1280x720, multiply by 1.5 for actual 1920x1080

## Data Seeding (seed_crm.py)

Uses XML-RPC API via `xmlrpc.client`:
```python
common = xmlrpc.client.ServerProxy('http://localhost:8069/xmlrpc/2/common')
uid = common.authenticate('odoodb', 'admin', 'admin', {})
models = xmlrpc.client.ServerProxy('http://localhost:8069/xmlrpc/2/object')
```

Records seeded:
- "Enterprise Software Licensing" (lead, BlueStar Technologies) — for convert_lead task
- "CloudServices Partnership" (opportunity, Vertex Solutions Corp) — for schedule_activity task
- "Digital Marketing Campaign" (opportunity, TechPulse Media) — for mark_opportunity_won task
- "Annual License Renewal", "Cloud Infrastructure Migration", "SaaS Platform Implementation" — background

## CRM Stages (stable IDs in this installation)

| Stage | ID | Sequence |
|-------|----|----------|
| New | 1 | 1 |
| Qualified | 2 | 2 |
| Proposition | 3 | 3 |
| Won | 4 | 70 (is_won=True) |

## 5 Tasks

| Task | Target Record | Start State |
|------|---------------|-------------|
| create_lead | Pacific Northwest Trading Co. - ERP Inquiry | CRM pipeline (record pre-deleted) |
| convert_lead_to_opportunity | Enterprise Software Licensing | Lead form with "Convert to Opportunity" button |
| schedule_activity | CloudServices Partnership | Opportunity form in Qualified stage |
| create_customer | Meridian Financial Group | Contacts kanban (record pre-deleted) |
| mark_opportunity_won | Digital Marketing Campaign | Opportunity form in Proposition stage with "Won" button |

## Debugging Tips

```bash
# Check Docker containers
docker ps

# Check Odoo logs
docker logs odoo-web --tail 50

# Check CRM data via curl (no auth for count)
curl -s http://localhost:8069/web/login | head -5  # should return HTML

# XML-RPC check
python3 -c "
import xmlrpc.client
c = xmlrpc.client.ServerProxy('http://localhost:8069/xmlrpc/2/common')
uid = c.authenticate('odoodb', 'admin', 'admin', {})
print('UID:', uid)  # should be 2
"

# Check Firefox rendering
pgrep -a firefox  # should show multiple processes (parent + content + socket)
```
