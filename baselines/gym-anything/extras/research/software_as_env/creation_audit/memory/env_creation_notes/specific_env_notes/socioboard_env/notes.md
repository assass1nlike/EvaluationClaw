> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Socioboard 4.0 Environment Notes

## Overview
Socioboard 4.0 — open source social media management platform.
- **Frontend**: Apache 2.4 + PHP 7.4 (Laravel 5.x) at `http://localhost`
- **Backend**: 4 Node.js (Express) microservices:
  - `socioboard-user` on port 3000 (auth, profile, teams)
  - `socioboard-publish` on port 3001 (social publishing)
  - `socioboard-feeds` on port 3002 (RSS, discovery, trends)
  - `socioboard-notification` on port 3003 (notifications)
- **Database**: MariaDB (database: `socioboard`) + MongoDB (database: `socioboard`)
- **Admin**: admin@socioboard.local / Admin2024!
- **Second user**: john.smith@socioboard.local / User2024! (for add_team_member task)

## CRITICAL: API_URL Configuration

### Double /v1/ Bug
PHP `.env` file MUST have `API_URL=http://127.0.0.1:3000/` WITHOUT `/v1/`.
PHP `TeamController` builds URL as: `env('API_URL') . env('VERSION') . '/'`
= `"http://127.0.0.1:3000/" + "v1" + "/" = "http://127.0.0.1:3000/v1/"`

If `API_URL=http://127.0.0.1:3000/v1/`, result is `"http://127.0.0.1:3000/v1/v1/"` → 404.

### API_URL_FEEDS Case Sensitivity
PHP helper reads `env('API_URL_FEEDS')` (uppercase) but `.env` file may have
`API_URL_FEEDs` (lowercase). Laravel `env()` is case-sensitive. BOTH must be in `.env`:
```
API_URL_FEEDs=http://127.0.0.1:3002/
API_URL_FEEDS=http://127.0.0.1:3002/
```

## CRITICAL: Sequelize isUrl Validator (localhost URLs)

The `user_details` Sequelize model uses `isUrl: { args: true }` for `profile_picture`.
This calls `validator.js isURL()` with `require_tld: true` by default.
`http://localhost/assets/imgs/user-avatar.png` FAILS because "localhost" has no TLD.

**Two-part fix required**:
1. In `user_details.js` model: `isUrl: { args: { require_tld: false }, ... }`
2. In `node_modules/sequelize/lib/utils/validator-extras.js`:
   ```js
   isUrl(str) {
     return this.isURL(str, { require_tld: false });
   }
   ```
   (The model-level `args` option is silently stripped by Sequelize v5's validator wrapper.)

## CRITICAL: Bash ! History Expansion in curl JSON

Sending `Admin2024!` password via bash double-quoted curl `-d` causes `!` history expansion.
**Fix**: Always use Python with `tempfile` for API calls with special characters:
```python
import subprocess, json, tempfile, os
body = {"user": "admin@socioboard.local", "password": "Admin2024!"}
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    json.dump(body, f)
    tmpfile = f.name
result = subprocess.run(
    ['curl', '-s', '-X', 'POST', '-H', 'Content-Type: application/json',
     '-d', '@' + tmpfile, 'http://127.0.0.1:3000/v1/login'],
    capture_output=True, text=True
)
os.unlink(tmpfile)
```

## CRITICAL: Team Creation API Format

The correct API endpoint and format:
```
POST http://127.0.0.1:3000/v1/team/create
Headers: x-access-token: <JWT>
Body: {"TeamInfo": {"name": "Team Name", "description": "description"}}
```

NOT `{"teamName": "..."}` — that returns HTML 400 "unexpected token" error.
First call `POST /v1/login` with `{"user": email, "password": pass}` to get JWT.

## CRITICAL: Default Team Required for Login

The Node.js user service's `getTeamNewSession()` is called after PHP login.
It calls `GET /v1/team/getDetails` — if user has no teams, this returns error.
PHP session setup fails → browser login shows "Something went wrong".

**Fix**: Create a default team via API immediately after registering the admin user.
The `POST /v1/register` (PUT method) does NOT auto-create a team.

## CRITICAL: User Plan (RSS Features)

RSS/Content Feeds features are gated by `user_activations.user_plan`:
- Plan 0 (Basic): `rss_feeds = 0` — RSS menu shows `planCheck(0)` instead of link
- Plan 2 (Premium): `rss_feeds = 1` — RSS menu shows the discovery link

Fix: `UPDATE user_activations SET user_plan = 2` (upgrades all users to Premium).

## PHP Patches Required

### settings.blade.php — Timezone Dropdown
The default settings form has no timezone field. Add `<select name="timeZone">` between
DOB and Bio rows with 10 timezone options. Pre-populate from `$userDetails->time_zone`
using safe access: `(isset($userDetails) && $userDetails && isset($userDetails->time_zone)) ? $userDetails->time_zone : ''`

### UserController.php — Three Fixes
1. **Phone validation nullable**: `'phone' => 'nullable|regex:/[0-9]{10}/'`
   (prevents "phone is invalid" error when phone field is empty)
2. **account() passes userDetails**: `return view('User::dashboard.settings', ['userDetails' => $userDetails])`
   (needed for timezone and name pre-population)
3. **timeZone in update call**: `"timeZone"=>$request->timeZone` added to profile update array

### TeamController.php — adminDetails Fallback
The `viewTeam()` method relies on PHP session data to find admin details. If a team
is created via API (not the PHP form), the session doesn't include it.
Fix: After the session loop, if `$adminDetails` is still empty, scan ALL session
`memberProfileDetails` to find the admin's profile by `user_id`.

### viewTeam.blade.php — Safe Access
Replace `{{$adminDetails['first_name']}}` with `{{isset($adminDetails['first_name']) ? ... : 'Admin'}}`
to prevent "Undefined index" 500 errors.

## Node.js Patches Required

### authorizedlibs.js — Fallback Values + time_zone
In `updateUserProfiles()`, the `user.update()` call must use fallback values to prevent
`notNull` violations when a field is not included in the form:
```js
return user.update({
    first_name: profileDetails.firstName || user.first_name,
    last_name: profileDetails.lastName || user.last_name,
    phone_code: profileDetails.phoneCode || user.phone_code,
    phone_no: profileDetails.phoneNumber || user.phone_no,
    about_me: profileDetails.aboutMe || user.about_me,
    time_zone: profileDetails.timeZone || user.time_zone,  // NEW
    // ...
});
```
Also add `'time_zone'` to the `findOne` attributes array.

### userlibs.js — time_zone in getUserDetails
Add `'time_zone'` to the `attributes` array in `getUserDetails()` so the PHP session
includes the user's timezone (needed for pre-population on settings page).

## RSS Feed Architecture

RSS feeds in Socioboard are **NOT stored in the database**. They are fetched on-demand
from the external RSS URL via the feeds microservice. The "Add Feed" action in the UI
calls `GET /v1/trends/getRssFeeds?rssUrl=...` and displays articles immediately.

Verifier uses `exec_in_env` to call the feeds API with the expected URL and checks
that articles are returned (proving the URL is accessible).

## Database Tables (MariaDB)

| Table | Purpose |
|-------|---------|
| `user_details` | User profiles (first_name, last_name, about_me, phone_no, time_zone) |
| `user_activations` | User activation, plan (user_plan=2 for Premium) |
| `team_informations` | Teams (team_name, team_admin_id) |
| `join_table_users_teams` | Team membership (invitation_accepted: 0=pending, 1=accepted) |
| `join_table_teams_social_accounts` | Social accounts linked to teams |
| `social_accounts` | Connected social media accounts |

## Key URLs

| URL | Purpose |
|-----|---------|
| `http://localhost/login` | Login page (agent task start) |
| `http://localhost/dashboard/1` | Dashboard for team 1 (default team) |
| `http://localhost/settings` | Account Settings (profile + timezone) |
| `http://localhost/discovery/rss-feed` | RSS/Content Feeds manager |
| `http://localhost/create-team` | Create a new team |
| `http://localhost/view-team/{id}` | View team, manage members |

## API Endpoints (Node.js)

All user service endpoints at `http://127.0.0.1:3000/v1/`:
- `POST /login` — `{"user": email, "password": pass}` → `{accessToken: "..."}`
- `PUT /register` — Register new user
- `POST /team/create` — `{"TeamInfo": {"name": "...", "description": "..."}}` + x-access-token
- `GET /team/getDetails` — All teams for current user + x-access-token
- `GET /team/getTeamDetails?TeamId=N` — Team N details + x-access-token
- `POST /team/invite?TeamId=N&Email=...&Permission=0` — Invite user + x-access-token

Feeds service at `http://127.0.0.1:3002/v1/`:
- `GET /trends/getRssFeeds?rssUrl=<encoded>` — Fetch RSS feed articles + x-access-token

## Tasks Summary (All Verified ✓)

### 1. create_team
- Pre-state: No "Digital Marketing Hub" team (deleted by setup_task.sh)
- UI flow: Login → Teams dropdown → Create Team → Enter name → Submit
- Alternative: POST /v1/team/create via Node.js API
- Verifier: `SELECT team_name FROM team_informations WHERE team_name = 'Digital Marketing Hub'`

### 2. update_user_profile
- Pre-state: first_name="Admin", last_name="User", about_me=NULL
- UI flow: Login → Settings (gear icon or /settings) → Edit Profile → Fill fields → Save
- Verifier: `SELECT first_name, last_name, about_me FROM user_details WHERE email = 'admin@socioboard.local'`

### 3. change_timezone
- Pre-state: `time_zone = 'NA'` (reset by setup_task.sh)
- UI flow: Login → Settings → Account Settings → Select timezone from dropdown → Save
- URL: `http://localhost/settings`
- Verifier: `SELECT time_zone FROM user_details WHERE email = 'admin@socioboard.local'`

### 4. add_rss_feed
- Pre-state: No feeds loaded
- UI flow: Login → Discovery → RSS (in nav) → Enter Feed Name + Feed URL → Add Feed
- URL: `http://localhost/discovery/rss-feed`
- Feed: BBC Technology News / https://feeds.bbci.co.uk/news/technology/rss.xml
- Verifier: Call feeds API and verify articles returned (feeds not stored in DB)

### 5. add_team_member
- Pre-state: "Content Strategy Team" pre-created by setup_task.sh via API
- UI flow: Login → Dashboard → (find Content Strategy Team) → View Team → Invite New Team Member → Enter email → Add
- URL: `http://localhost/view-team/{team_id}` (team_id varies per run)
- CRITICAL: Agent must discover the team_id. Team appears in dashboard team selector.
- Verifier: `SELECT jt.invitation_accepted FROM join_table_users_teams jt ... WHERE email = 'john.smith@socioboard.local'`

## Known Limitation: add_team_member Team Discovery

The agent must navigate to the "Content Strategy Team" but doesn't know the team_id.
The team appears in the top navigation's team dropdown (if it was refreshed). However,
since the team is created via API (not PHP form), the PHP session may not include it.

**Workaround**: The agent can:
1. Use the create-team page to see all teams in the dropdown
2. Or navigate directly if they can see the team name in the nav

Consider improving setup_task.sh to also trigger a PHP session refresh by visiting
`/create-team` which calls `team/getDetails` to rebuild the session.

## SSH Access

VM SSH: `sshpass -p 'password123' ssh -p {SSH_PORT} -o StrictHostKeyChecking=no -o PubkeyAuthentication=no ga@localhost`
Default SSH port for this environment: 2369 (varies per QEMU instance)
