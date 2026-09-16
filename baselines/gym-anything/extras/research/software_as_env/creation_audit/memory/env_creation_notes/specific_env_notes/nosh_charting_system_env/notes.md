> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# NOSH ChartingSystem Environment — nosh_charting_system_env

**Status**: FULLY VERIFIED 2026-02-23 (interactive VNC testing; checkpoint rebuilt with other_history AUTO_INCREMENT fix)
**Base env**: Copied from `nosh_env` (identical scripts, 10 new tasks)

---

## Stack

Docker Compose (inside QEMU Ubuntu 22.04 VM):
- **nosh-app**: `shihjay2/nosh2:latest` (PHP-FPM:9000, Laravel 5.x)
- **nosh-nginx**: nginx reverse proxy on `:80`
- **nosh-db**: `mariadb:10.11` (DB name: `nosh`, root: `rootpassword`, user: `asuser/noshpassword`)
- **URL**: `http://localhost/login`

## Credentials

| Account | Username | Password | Group |
|---------|----------|----------|-------|
| Admin | `admin` | `Admin1234!` | 1 (admin) |
| Provider | `demo_provider` | `Provider1234!` | 2 (provider) |
| Practice | "Hillside Family Medicine" | — | practice_id=1 |

**IMPORTANT**: Login form requires `practice_id=1` field in addition to username+password (NOSH validates the practice dropdown). For curl-based testing:
```bash
curl -X POST http://localhost/login \
  -F "_token=$CSRF" -F "username=demo_provider" -F "password=Provider1234!" -F "practice_id=1"
```

**IMPORTANT**: Use `demo_provider` (not admin) for ALL clinical tasks. Admin (group_id=1) cannot see the `+` add buttons in chart sections.

## Patients

20 Synthea-generated Massachusetts patients, PIDs 1-20.

| PID | Name | DOB | Sex |
|-----|------|-----|-----|
| 1 | Conchita Hernandes | 2006-12-04 | F |
| 2 | Corine Ziemann | 2000-11-29 | F |
| 3 | Crysta Parisian | 2005-03-26 | F |
| 4 | Charles Nolan | 2003-11-02 | M |
| 5 | Kent Zemlak | 2001-02-16 | M |
| 6 | Dwight Dach | 1998-03-21 | M |
| 7 | Ezequiel Hermiston | 2002-05-19 | M |
| 8 | Denny Lubowitz | 2000-07-04 | F |

## Key DB Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `demographics` | Patients | `pid`, `fname`, `lname`, `sex` ('m'/'f'), `DOB` |
| `other_history` | Social/Family history | `pid`, `eid` (0=standalone), `oh_sh`, `oh_fh`, `oh_tobacco` |
| `rx_list` | Medications | `pid`, `rxl_medication`, `rxl_dosage`, `rxl_dosage_unit`, `rxl_date_inactive` (NULL=active) |
| `schedule` | Appointments | `appt_id`, `pid`, `start` (unix INT), `end` (unix INT), `visit_type`, `status`, `title` |
| `orders` | Lab/referral orders | `pid`, `orders_labs` (longtext), `orders_referrals` (longtext) |
| `insurance` | Insurance records | `pid`, `ins_company`, `ins_group`, `ins_member` |
| `messaging` | Internal messages | `pid`/`message_from`, `subject`, `body` |
| `practiceinfo` | Practice config | `email`, `weekends`, `minTime`, `maxTime`, calendar fields |
| `encounters` | Clinical encounters | `pid`, `encounter_DOS` |
| `providers` | Provider info | `id`=2 (demo_provider), `specialty`, `schedule_increment`='20' |

## Key Routes

| Route | Page | Notes |
|-------|------|-------|
| `/login` | Login | Requires `practice_id` field in POST |
| `/` or `/dashboard` | Dashboard | Shows after login |
| `/set_patient/{pid}` | Set active patient | Navigate here first |
| `/social_history` | Social History | Writes to `other_history` (eid=0) |
| `/family_history` | Family History | Writes to `other_history` (eid=0) |
| `/medications_list/active` | Active Medications | Reads from `rx_list` |
| `/payors_list/active` | Insurance/Payers | Reads from `insurance` |
| `/messaging/inbox` | Messaging | Reads from `messaging` |
| `/orders_list/orders_labs` | Lab Orders | Reads from `orders` |
| `/orders_list/orders_referrals` | Referral Orders | Reads from `orders` |
| `/schedule` | Calendar/Schedule | FULL calendar, uses FullCalendar |
| `/practice_manage/edit` | Edit Practice | Admin or configure menu |
| `/encounters_list` | Encounters | List of encounters for active patient |

## Critical Setup Notes

### Password Hash Issue (SOLVED)
The `setup_nosh.sh` generates bcrypt hashes via `php -r "echo password_hash('Provider1234!', ...)"`. If this fails, a fallback hash is used. The checkpoint was rebuilt fresh and verified to have working hashes. If login fails in a new checkpoint, regenerate hashes:
```bash
# SCP this PHP file to VM and run in nosh-app container
docker exec nosh-app php /tmp/update_pass.php
# Content of update_pass.php:
# $pdo = new PDO('mysql:host=nosh-db;dbname=nosh', 'asuser', 'noshpassword');
# $ph = password_hash('Provider1234!', PASSWORD_BCRYPT);
# $pdo->exec("UPDATE users SET password='".addslashes($ph)."' WHERE username='demo_provider'");
```

### Providers Table Required
The `providers` table must have a row with `id=2` for demo_provider. Without it, the dashboard returns 500 error on `/users/2/1` and `schedule_increment` property access. Verified populated in current checkpoint.

### Checkpoint Rebuild (CRITICAL)
To rebuild the checkpoint after script changes:
1. **DELETE** the checkpoint file: `rm ~/.cache/gym-anything/qemu/checkpoint_dae5fd2ea53af392_post_start.qcow2`
2. Run `env.reset(seed=42, use_cache=True, cache_level='post_start', use_savevm=True)` — since no checkpoint exists, it rebuilds and **saves** a new checkpoint

**DO NOT** use `use_cache=False` to rebuild — it runs all hooks but does NOT save the checkpoint.

### Calendar Required for Schedule Page
`practiceinfo` must have `weekends`, `minTime`, `maxTime`, timezone, and `mon_o`/`mon_c`-`fri_o`/`fri_c` fields set. The `calendar` table must have the `Office Visit` visit type. Both set in `setup_nosh.sh`.

## 10 Tasks

| # | Task | Patient | Pre-seeded Data | Provider |
|---|------|---------|-----------------|----------|
| 1 | `add_social_history` | Conchita Hernandes (pid=1) | None | demo_provider |
| 2 | `add_family_history` | Corine Ziemann (pid=2) | None | demo_provider |
| 3 | `add_insurance` | Crysta Parisian (pid=3) | None | demo_provider |
| 4 | `cancel_appointment` | Charles Nolan (pid=4) | 1 appointment (2026-07-15 10:00) | demo_provider |
| 5 | `order_lab_test` | Kent Zemlak (pid=5) | None | demo_provider |
| 6 | `document_hpi` | Dwight Dach (pid=6) | None | demo_provider |
| 7 | `update_practice_email` | — (admin task) | email reset to `admin@hillsidefm.local` | admin |
| 8 | `add_referral` | Ezequiel Hermiston (pid=7) | None | demo_provider |
| 9 | `discontinue_medication` | Denny Lubowitz (pid=8) | 1 active Metformin 500mg | demo_provider |
| 10 | `send_message` | — (provider task) | None | demo_provider |

## Critical Bug Fixed (2026-02-23)

### other_history AUTO_INCREMENT Missing
The `other_history.oh_id` primary key column was missing `AUTO_INCREMENT`. When NOSH's family/social history controller tried to create a persistent baseline row (eid=0) for any patient after the first, it failed with:
```
SQLSTATE[23000]: Integrity constraint violation: 1062 Duplicate entry '0' for key 'PRIMARY'
(SQL: insert into `other_history` (`eid`, `pid`) values (0, 2))
```
**Fix**: Added to `scripts/setup_nosh.sh` after patient data loading:
```bash
ALTER TABLE other_history MODIFY oh_id bigint(20) NOT NULL AUTO_INCREMENT;
```
**Checkpoint rebuild required** after this fix (see below).

### Practice Information URL
The practice email settings page is at `/core_form/practiceinfo/practice_id/1/information` (not `/practice` which returns 404, nor `/setup/1` which redirects to billing).

### Lab/Referral Orders URL Format
The orders list URL is `/orders_list/{type}` where type must be one of:
- `orders_labs` — Lab orders
- `orders_radiology` — Radiology
- `orders_cp` — Cardiopulmonary
- `orders_referrals` — Referrals

## Verification Results (2026-02-23, Interactive VNC testing)

All 10 tasks verified interactively:
- ✅ Login page loads at `http://localhost/login` with "Hillside Family Medicine" dropdown
- ✅ Login with demo_provider/Provider1234!/practice_id=1 redirects to dashboard
- ✅ Dashboard shows Dr. James Carter's view with 0 counts for all widgets
- ✅ Social History empty for pid=1 (add_social_history start state) — `07_add_social_history_start_state.png`
- ✅ add_social_history task completed end-to-end with "updated!" banner — `09_add_social_history_completed.png`
- ✅ Family History accessible for pid=2 after AUTO_INCREMENT fix — `16_add_family_history_start_state.png`
- ✅ Insurance/Payers empty for pid=3 (add_insurance start state) — `12_add_insurance_empty_payers.png`
- ✅ Appointment pre-seeded in schedule for pid=4: July 15 2026 10:00 — `10_cancel_appointment_preseeded.png`
- ✅ Lab orders empty for pid=5 (order_lab_test start state) — `17_order_lab_test_empty_orders.png`
- ✅ Encounters empty for pid=6 (document_hpi start state) — `18_document_hpi_empty_encounters.png`
- ✅ Practice info email=admin@hillsidefm.local (update_practice_email start state) — `13_update_practice_email_start_state.png`
- ✅ Referrals empty for pid=7 (add_referral start state) — `19_add_referral_empty_orders.png`
- ✅ Metformin 500mg active in rx_list for pid=8 — `11_discontinue_medication_preseeded.png`
- ✅ Messaging inbox accessible with "+ New Message" button — `14_send_message_inbox.png`
- ✅ New Message compose form has To/Subject/Message/CC fields — `15_send_message_compose_form.png`

## env_hash

`dae5fd2ea53af392` (checkpoint path: `~/.cache/gym-anything/qemu/checkpoint_dae5fd2ea53af392_post_start.qcow2`)
