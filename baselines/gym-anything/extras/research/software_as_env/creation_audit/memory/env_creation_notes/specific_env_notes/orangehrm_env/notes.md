> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OrangeHRM Environment Notes

## Overview

OrangeHRM 5.8 Community Edition HR management system. Docker-in-QEMU deployment via docker-compose.

## Deployment

- **Docker images**: `orangehrm/orangehrm:5.8` + `mariadb:10.11`
- **Port**: 8000 (HTTP)
- **Containers**: `orangehrm` (PHP/Apache) + `orangehrm-db` (MariaDB)
- **DB credentials**: `orangeuser` / `orangepass123`, root: `rootpass123`, DB: `orangehrm`
- **Admin**: `admin` / `Admin@OHrm2024!`

## Installation Flow (pre_start)

`install_orangehrm.sh` runs a CLI installer (`console orangehrm:install`) inside the container. Key points:
- Container must be running (started in install script itself)
- Installer uses `ADMIN_PASS_INSTALL="Admin1234!"` — separate from the runtime password
- After install, post_start (`setup_orangehrm.sh`) changes password via PHP PDO

## CRITICAL: Password Update via PHP PDO

The admin password `Admin@OHrm2024!` contains `@` which is fine, but bcrypt hashes in `$2y$10$...` format contain `$` characters that get shell-expanded if you try to set them in a bash variable. The fix is to generate the hash INSIDE the PHP command:

```bash
docker exec orangehrm php -r "
\$pdo = new PDO('mysql:host=orangehrm-db;dbname=orangehrm', 'orangeuser', 'orangepass123');
\$hash = password_hash('Admin@OHrm2024!', PASSWORD_BCRYPT);
\$stmt = \$pdo->prepare(\"UPDATE ohrm_user SET user_password=? WHERE user_name='admin'\");
\$stmt->execute([\$hash]);
echo 'Updated: ' . \$stmt->rowCount() . \" rows\n\";
\$pdo->exec('DELETE FROM ohrm_enforce_password');
" 2>/dev/null
```

## CRITICAL: Leave Period Configuration

OrangeHRM requires leave period to be configured before any leave can be assigned/applied. Without it, the Assign button gives HTTP 500 with `cannotAssignLeaveBeyondMaxAllowedLeavePeriodEndDate` (null endDate).

**Two things required**:
1. `hs_hr_config`: insert `('leave_period_defined', 'Yes')`
2. `ohrm_leave_period_history`: insert `(leave_period_start_month=1, leave_period_start_day=1, created_at=today)`

Done in `setup_orangehrm.sh` section 6b and also in `apply_leave/setup_task.sh` as a safety check.

## CRITICAL: Leave Requests — No `deleted` Column

`ohrm_leave_request` has no `deleted` column. Pre-task soft-delete won't work. Must hard-delete:

```bash
DELETE FROM ohrm_leave WHERE emp_number=${EMP_NUM};
DELETE FROM ohrm_leave_request WHERE emp_number=${EMP_NUM};
```

## CRITICAL: Leave Assignment Only Works on Weekdays

OrangeHRM returns "Failed to Submit: No Working Days Selected" if you try to assign leave on a Saturday or Sunday. The pre-task `apply_leave/setup_task.sh` calculates the **next working weekday** using Python:

```python
from datetime import date, timedelta
d = date.today() + timedelta(days=1)
while d.weekday() >= 5:  # 5=Sat, 6=Sun
    d += timedelta(days=1)
```

## Browser Interaction Notes

- **Browser**: Firefox snap (pre-installed in ubuntu-gnome-systemd base image)
- **Profile**: `/home/ga/.mozilla/firefox/default.profile/` — configured in post_start
- **Firefox window ID**: found via `xdotool search --class Firefox`, typically 8388611
- **VNC resolution**: 1920x1080
- **VG coordinate mapping**: VG (x, y) in 1280×720 → actual desktop (x×1.5, y×1.5)
- **Assign button in unscrolled form**: VG ~(1195, 502) → actual ~(1793, 753)
- **CRITICAL**: If you accidentally open the "Browser Console" (Ctrl+Shift+J), it blocks mouse clicks. Close via `wmctrl -ic <window_id>` before clicking UI elements.
- **Firefox window position**: starts at desktop (70, 64), size 1850×1016

## Login / ensure_orangehrm_logged_in

`ensure_orangehrm_logged_in()` in `task_utils.sh`:
1. Checks if already on target URL
2. If not, navigates to login page
3. Clicks username field at ~(813, 596), types admin username
4. Tabs to password field at ~(813, 683), types password
5. Clicks "Login" button at ~(813, 770)
6. Navigates to target URL

## URL Patterns (OrangeHRM 5.x SPA)

All routes are under `/web/index.php/`:
- **Add Employee**: `/pim/addEmployee`
- **Job Titles**: `/admin/viewJobTitleList`
- **Leave Types**: `/leave/leaveTypeList` (NOT `viewLeaveTypeList`)
- **Employee Contact**: `/pim/contactDetails/empNumber/{N}`
- **Assign Leave**: `/leave/assignLeave` (admin assigns to employee)
- **Apply Leave**: `/leave/applyLeave` (employee's own — won't work for admin who has no employee profile)

## Seed Data

After post_start seeding:
- **20 employees**: EMP001-EMP020, including:
  - EMP001: James Anderson (Software Engineer)
  - EMP002: Sarah Mitchell (HR Manager)
- **8 job titles**: Software Engineer, HR Manager, Financial Analyst, Marketing Specialist, Operations Manager, Product Manager, Data Scientist, UX Designer
- **5 leave types**: Annual Leave, Sick Leave, Personal Leave, Maternity Leave, Paternity Leave
- **6 departments**: Engineering, Human Resources, Finance, Marketing, Operations, Product Management
- **Leave entitlements**: 15 days Annual Leave for each employee (current year)
- **Admin user**: emp_number=1

## Tasks

| # | Task | Start State | Action |
|---|------|-------------|--------|
| 1 | add_employee | Admin > PIM > Add Employee form | Add Marcus Rivera / MR-022 |
| 2 | create_job_title | Admin > Job > Job Titles list (11 entries) | Add Cloud Architect |
| 3 | add_leave_type | Leave > Configuration > Leave Types (5 entries) | Add Bereavement Leave |
| 4 | update_employee_contact | James Anderson (EMP001) Contact Details; work phone reset to 212-555-0101 | Update work phone to 646-555-9900 |
| 5 | apply_leave | Leave > Assign Leave form (blank) | Assign Annual Leave for Sarah Mitchell on next workday |

## Timing

- **pre_start** (install_orangehrm.sh): ~3-5 min (Docker pull + CLI install)
- **post_start** (setup_orangehrm.sh): ~2-3 min (DB seed, Firefox warm-up)
- **pre_task**: ~10-20s per task (login + navigate)

## Debugging

DB queries via:
```bash
docker exec orangehrm-db mysql -u orangeuser -porangepass123 orangehrm -e "QUERY"
```

App logs at: `/var/www/html/src/log/orangehrm.log` (inside container)

Apache access log: `docker logs orangehrm 2>&1 | tail -20`
