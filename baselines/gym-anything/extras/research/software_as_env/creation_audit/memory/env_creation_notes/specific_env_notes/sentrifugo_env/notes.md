> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Sentrifugo HRMS Environment Creation Notes

## Application Details

- Sentrifugo v3.2 - Open source HRMS (PHP/MySQL, Zend Framework 1)
- Downloaded from SourceForge (fallback: GitHub)
- Requires PHP 7.4 (not compatible with PHP 8.x)
- MySQL 5.7 via Docker container inside QEMU VM
- Apache with mod_rewrite for URL routing

## Key Technical Discoveries

### Password Hashing (CRITICAL)

- Sentrifugo `Login/Auth.php` uses plain `md5(password)` WITHOUT the auth salt
- The `auth.salt` in `application.ini` is read but NOT used for password hashing in the login adapter
- Code: `$password=md5($password);` in `Login/Auth.php` line ~52 (both 'db' and 'email' cases)
- All other password operations (`UsermanagementController`, `EmployeeController`, `DashboardController`) also use plain `md5()`
- This was a major debugging challenge - initially we computed `MD5(CONCAT(password, salt))` which caused "incorrect password" errors

### Password Field Maxlength

- The login form password field has `maxlength="15"` in HTML
- Original password `Admin@Sfugo2024!` (16 chars) exceeded this limit
- Changed to `Admin@Sfugo24` (13 chars) to fit within the constraint

### DocumentRoot Configuration

- Sentrifugo's `index.php` is at the ROOT directory, NOT in `public/`
- Unlike typical Zend Framework apps, DocumentRoot must point to `/var/www/html/sentrifugo`, not `/var/www/html/sentrifugo/public`
- The `.htaccess` with RewriteEngine rules must be at the root level

### db_constants.php

- Sentrifugo's `index.php` requires both sets of PHP constants:
  - `SENTRIFUGO_HOST`, `SENTRIFUGO_DBNAME`, `SENTRIFUGO_USERNAME`, `SENTRIFUGO_PASSWORD`
  - `ABOREDHOST`, `ABOREDDBNAME`, `ABOREDUSER`, `ABOREDPASSWORD`
- File location: `/var/www/html/sentrifugo/public/db_constants.php`

### Authentication Flow

- Login form accepts either email or employeeId as username
- If input passes `FILTER_VALIDATE_EMAIL`, uses 'email' adapter (looks up by `emailaddress` column)
- Otherwise uses 'db' adapter (looks up by `employeeId` column)
- After login, first-time users are redirected to `/managemodule` (module configuration page)
- Setting `tourflag=1` in `main_users` skips the first-login tour

### Pay Frequency Table (CRITICAL for Job Title Dropdown)

- `getJobTitleList()` in `Jobtitles.php` does an `INNER JOIN` with `main_payfrequency` on `jobpayfrequency=p.id`
- If `main_payfrequency` is empty OR job titles don't have `jobpayfrequency` set, the dropdown shows "Job titles are not configured yet."
- Fix: seed `main_payfrequency` with at least one record (e.g., Annual, Monthly, Hourly) and set `jobpayfrequency` on all job titles

### main_employees Table (CRITICAL for Employee List)

- The `/employee` page checks `getCurrentOrgHead()` which queries `main_employees WHERE is_orghead=1`
- If no org head exists, the page shows the "add organization head" form instead of the employee list
- `main_employees` is a separate table from `main_users` and `main_employees_summary`
- Must seed `main_employees` with all user records AND set `is_orghead=1` for at least one user (typically admin)
- Fields: `user_id, date_of_joining, reporting_manager, emp_status_id, businessunit_id, department_id, jobtitle_id, position_id, prefix_id, is_orghead`

### Dashboard 503 Error (Non-blocking)

- The `/dashboard` page throws a 503 "Application error" because dashboard-related tables (main_dashboards, main_dashboardpriviledges, main_dashboard_widgets) don't exist in the `hrms.sql` schema
- The DashboardController uses Doctrine ORM to load dashboard widgets/privileges
- This is non-blocking: task setup scripts navigate directly to target URLs, bypassing the dashboard

### Employee/User Structure

- `main_users` table contains login credentials and basic info
- `main_employees_summary` table contains HR details (department, job title, etc.)
- `main_employees` table links users to org structure (required for employee list view)
- `emprole=1` is super admin, `emprole=5` is regular employee
- `userstatus='old'` means active user (vs 'new' for pending)
- `isactive=1` required for login

### Browser Login Automation

- xdotool coordinates for 1920x1080 login page:
  - Username field: (990, 584)
  - Password field: Tab from username
  - Submit: Enter key after password
- Must run `xdotool windowfocus --sync` before interacting
- Login form renders consistently at these coordinates on the maximized Firefox window

## Seeded Data

- Organization: "Acme Global Technologies"
- 3 business units, 8 departments, 16 job titles, 8 positions
- 4 employment statuses, 20 employees (EMP001-EMP020)
- 6 leave types, 1 holiday group with 8 US federal holidays
- Admin: admin@sentrifugo.local / Admin@Sfugo24

## Five Tasks Created

1. add_employee - Add employee EMP021 "Marcus Chen" (easy)
2. configure_leave_type - Add "Bereavement Leave" (easy)
3. create_department - Create "Research & Development" department (easy)
4. update_employee_designation - Change James Anderson's job title (easy)
5. manage_holiday_calendar - Add Veterans Day holiday (easy)

## Base Image

- ubuntu-gnome-systemd_highres (1920x1080)
- Resources: 4 CPU, 8GB RAM, GPU: 0, Network: enabled
