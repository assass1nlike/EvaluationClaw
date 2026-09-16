> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# iDempiere Environment Notes

## Installation
- Docker image: `idempiereofficial/idempiere:12-release` + `postgres:16`
- Port 8080 (HTTP) and 8443 (HTTPS) both work, but browser should use HTTPS
- iDempiere v12 "Kudos" — current LTS release (Jan 2025)
- Docker Compose v2 required (`docker compose`, not `docker-compose`)
- Java is bundled inside the Docker image (JDK 17)
- No Oracle DB support in Docker image — PostgreSQL only

## First Launch
- First container start seeds the GardenWorld demo database automatically
- In practice (with cached Docker images): ~3-4 minutes total startup time
- Cold pull of images: may add 5-10 minutes
- Health check: `curl -k -s https://localhost:8443/webui/` → HTTP 200

## Access
- URL: `https://localhost:8443/webui/`
- Self-signed SSL certificate — browser shows security warning on first access

## Login Flow (4 steps, confirmed at 1920x1080)
1. **SSL warning page**: Click "Advanced..." at (1319, 752), then "Accept the Risk and Continue" at (1251, 1038)
2. **Login form**: User field (1245, 606), Password field (1245, 639), OK button (1344, 825)
3. **Role selection page**: Confirm OK at (1230, 858) — GardenWorld/GardenWorld Admin pre-selected
4. **Dashboard** appears

## Credentials
- `GardenAdmin` / `GardenAdmin` → GardenWorld company, GardenWorld Admin role
- `GardenUser` / `GardenUser` → GardenWorld company, Clerk role (limited access)
- `SuperUser` / `System` → All clients, super admin access
- `System` / `System` → System client only

## ZK Navigation Guard
- iDempiere uses ZK framework which intercepts browser navigation
- When navigating away (Ctrl+L + new URL + Enter), Firefox shows "Leave this page?" dialog
- **Click "Leave page"** at actual (1137, 656) to dismiss — add 2s sleep before clicking
- This appears every time you navigate to a new URL while iDempiere is loaded

## Database Queries
```bash
# Direct PostgreSQL queries via Docker
docker exec idempiere-postgres psql -U adempiere -d idempiere -t -A -c "SQL_HERE"

# GardenWorld client_id = 11
# Key tables:
# c_bpartner  — Business Partners (customers/vendors)
# c_order     — Sales/Purchase Orders (issotrx='Y'=sales, 'N'=purchase)
# m_product   — Products
# c_invoice   — Invoices
# gl_journal  — GL Journal headers
# gl_journalline — GL Journal lines
# c_elementvalue — Chart of Accounts (GL accounts)
# ad_client   — Clients (GardenWorld = id 11)
```

## GardenWorld Demo Data (as of iDempiere 12)
**Customers (iscustomer='Y'):**
- C&W Construction, Agri-Tech, Joe Block, Patio Fun Inc., Seed Farm Inc., GardenUser BP, Standard

**Vendors (isvendor='Y'):**
- Seed Farm Inc., Tree Farm Inc., Chrome Inc., Color Inc., Wood Inc., Chemical Product Inc., Patio Fun Inc.

**Key Products:**
- Mulch 10# (value: Mulch), Fertilizer #50 (value: Fertilizer#50), Fertilizer #70
- Azalea Bush, Holly Bush, Rose Bush, Elm Tree, Oak Tree, Plum Tree
- Patio Table, Patio Chair, Patio Sun Screen, Patio Furniture Set
- Grass Seed Container, Grass Seeder, Lawn Tiller, Hoe 4 ft, Rake Bamboo, Rake Metal, Weeder

**Product Categories:** Bushes, Trees, Chemicals, Patio, Tools, Raw Material, Assembly, Standard, etc.

**GL Accounts (expense):** 62100 Media Advertising, 62200 Catalog/Newsletter, 61100 Rent Expense
**GL Accounts (cash):** 11100 Checking Account, 11200 Checking Account 2, 11900 Petty Cash

## UI Navigation Notes
- **Main Menu**: Hamburger icon or left sidebar has functional areas:
  - Quote-to-Invoice → Sales Order
  - Requisition-to-Invoice → Purchase Order
  - Partner Relations → Business Partner
  - Material Management → Product
  - Financial Management → Accounting → GL Journal
- **Favorites** on left sidebar: Sales Order at ~(165, 262), Business Partner at ~(165, 287), Product at ~(143, 335)
- **ZK UI**: All interactions go through browser; behaves like desktop app

## ZK Form Navigation (CRITICAL - confirmed via interactive testing)
- Clicking a window in Favorites always opens it in **QUERY MODE** (search form), NOT edit mode
- **To create a new record**: Execute empty query first (click ✓ at VG 1060,462 → actual 1590,693) to reach form view, THEN click the green **+** New button
- **Ctrl+Alt+N does NOT work from query mode** — must be in form/grid view first
- **NEVER use Ctrl+S** to save — Firefox intercepts it and opens "Save Page As" dialog
- **Toolbar buttons** (at VG y=167 → actual y=251, all confirmed in form view):
  - Find/Search: VG (356,167) → actual (534,251)
  - New Record (green +): VG (395,167) → actual (593,251)
  - Copy: VG (416,167) → actual (624,251)
  - Delete: VG (436,167) → actual (654,251)
  - Undo: VG (466,167) → actual (699,251)
  - Save (disk icon): VG (487,167) → actual (731,251)
- **Query execute button** (bottom right of query form): VG (1060,462) → actual (1590,693)
- **Form fields** (Search Key, Name) in BP form:
  - Search Key: VG (389,257) → actual (584,386)
  - Name: VG (389,286) → actual (584,429)
- Always **explicitly click** each field before typing — don't rely on Tab alone

## Env Reset Timing
- Fresh run: ~230s total (pre_start ~90s, post_start ~125s, pre_task ~15s)
- `use_cache=True, cache_level="post_start"` runs in ~60s total

## Docker Hub Rate Limits
- Anonymous Docker pulls hit rate limits on fresh QEMU boots
- Credentials are loaded from an env-local file referenced via
  `EnvSpec.security.secrets_ref` (or a mounted `config/.dockerhub_credentials`
  that is gitignored). Set `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` there;
  do **not** commit either to this notes file.

## Post-Start Checkpoint State
- Checkpoint `checkpoint_aadc8080200860fa_post_start.qcow2` (~11GB) exists
- Firefox is on **SSL warning page** in the checkpoint (not yet past SSL)
- Every test must handle SSL: click "Advanced..." at (1319,752), then "Accept Risk" at (1251,1038)
- Must also re-focus Firefox: `xdotool windowfocus --sync <FF_WIN>` before SSL clicks
- SSH password: `password123` (NOT `GymAnything123!`)

## Common Issues
- **SSL cert warning** — must click through on first Firefox launch (setup handles it)
- **Leave page dialog** — ZK framework shows this on every URL navigation (handled in task_utils.sh)
- **Docker Compose v2** — must use `docker compose` not `docker-compose`
- **PostgreSQL auth** — app connects as `adempiere`/`adempiere` to `idempiere` database
- **certutil** — certutil can be used to import SSL cert to Firefox profile (reduces click automation)
- **BP window opens in query mode** — see ZK Form Navigation section above
