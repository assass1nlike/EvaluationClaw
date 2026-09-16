> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenSIS Environment Setup Guide

## Overview

OpenSIS (Open Student Information System) is a web-based PHP application that requires a full LAMP stack (Linux, Apache, MySQL/MariaDB, PHP). This document details the setup process and critical configurations discovered during implementation.

## Requirements

- **Operating System**: Ubuntu 22.04 (tested on ubuntu-gnome-systemd_highres base image)
- **Web Server**: Apache 2.4+
- **Database**: MariaDB 10.4+ or MySQL 8.0+
- **PHP**: 8.x with extensions: mysqli, gd, curl, mbstring, xml, zip, intl
- **Browser**: Chrome/Chromium for UI automation

## Installation Approach

### Recommended: Automated Web Installer

OpenSIS has a built-in web installer that normal users run to set up the application. This is the **recommended approach** as it properly handles all database setup, password hashing, and relationships.

The `automate_installer.py` script automates the 5-step web installer:
1. **Step 1**: Database credentials (server, port, user, password)
2. **Step 2**: Create database (name, fresh/existing)
3. **Step 3**: School info (name, dates, sample data option)
4. **Step 4**: Admin account (name, email, username, password)
5. **Step 5**: Completion (writes Data.php, cleanup)

**Default credentials after automated installation:**
- **Username**: admin
- **Password**: Admin@123

### Alternative: Manual Database Setup

Manual setup is NOT recommended as it requires:
- Correct password hashing using OpenSIS's functions
- Multiple related database records
- Exact module permission entries

If automated installation fails, the setup script falls back to manual setup.

## Installation Process

### 1. LAMP Stack Installation (install_opensis.sh)

The installation script handles:
- Apache2 web server
- MariaDB database server
- PHP 8.x with required extensions
- Chrome browser
- Selenium for installer automation
- OpenSIS v9.2 from GitHub releases

### 2. Configuration (setup_opensis.sh)

The setup script handles:
- Starting MariaDB and Apache services
- Running automated web installer (via Selenium)
- Apache virtual host configuration
- File permissions
- Chrome browser launch

## Critical Configuration Details

### Database Configuration

OpenSIS uses `Data.php` for database credentials (NOT DatabaseInc.php directly):

```php
<?php
$DatabaseType = 'mysqli';
$DatabaseServer = 'localhost';
$DatabaseUsername = 'opensis_user';
$DatabasePassword = 'opensis_password_123';
$DatabaseName = 'opensis';
$DatabasePort = '3306';
?>
```

### Password Hashing

OpenSIS uses its own password hashing functions in `functions/PasswordHashFnc.php`. The correct way to generate a password hash:

```bash
php -r 'include "/var/www/html/opensis/functions/PasswordHashFnc.php"; echo GenerateNewHash("admin123");'
```

**DO NOT** use generic bcrypt hashes - OpenSIS's VerifyHash function may not accept them.

### Required Database Records

#### 1. login_authentication
```sql
INSERT INTO login_authentication (user_id, username, password, profile_id, failed_login)
VALUES (1, 'admin', '<hash>', 1, 0);
```
- `profile_id` MUST be 1 (Administrator), NOT 0
- `failed_login` MUST be 0 to prevent lockout

#### 2. staff
```sql
-- The USER_ID column must exist and be populated
ALTER TABLE staff ADD COLUMN IF NOT EXISTS USER_ID int(11) DEFAULT NULL;

INSERT INTO staff (staff_id, current_school_id, first_name, last_name, profile_id, USER_ID)
VALUES (1, 1, 'Admin', 'User', 1, 1);
```
- `USER_ID` MUST match `login_authentication.user_id`
- `profile_id` MUST be 1

#### 3. staff_school_info
```sql
INSERT INTO staff_school_info (staff_id, category, home_school, opensis_access, opensis_profile)
VALUES (1, 'Administrator', 1, 'Y', 'admin');
```
- `opensis_access` MUST be 'Y' for login to work

#### 4. staff_school_relationship (CRITICAL!)
```sql
-- This record is ESSENTIAL - without it, queries fail with empty SCHOOL_ID
INSERT INTO staff_school_relationship (staff_id, school_id, syear)
VALUES (1, 1, <CURRENT_YEAR>);  -- Must use dynamic year!
```
**WARNING:** If this record is missing, you get "DB Execute Failed" errors after login.

#### 5. school_years (CRITICAL - dates must cover current date!)
```sql
-- The date range MUST include today's date
-- OpenSIS query: SELECT ... WHERE CURDATE() BETWEEN START_DATE AND END_DATE
INSERT INTO school_years (marking_period_id, syear, school_id, title, start_date, end_date, ...)
VALUES (1, <CURRENT_YEAR>, 1, '2025-2026', '2025-08-01', '2026-06-30', ...);

-- Also update schools.syear to match
UPDATE schools SET syear = <CURRENT_YEAR> WHERE id = 1;
```
**WARNING:** If today's date is outside start_date/end_date range, login fails with "DB Execute Failed".

#### 5. profile_exceptions (Module Permissions)
```sql
-- Module names MUST match EXACTLY what's in modules/*/Menu.php
INSERT INTO profile_exceptions (profile_id, modname, can_use, can_edit) VALUES
(1, 'students/Student.php', 'Y', 'Y'),
(1, 'students/Student.php&include=GeneralInfoInc&student_id=new', 'Y', 'Y'),
-- ... etc
```

## Automatic School Year Calculation

The `direct_db_setup.sh` script automatically calculates the correct school year based on the current date:

```bash
# From direct_db_setup.sh
CURRENT_YEAR=$(date +%Y)
CURRENT_MONTH=$(date +%m)

# If we're in Aug-Dec, school year is CURRENT-NEXT, else PREV-CURRENT
if [ "$CURRENT_MONTH" -ge 8 ]; then
    SCHOOL_YEAR_START=$CURRENT_YEAR
    SCHOOL_YEAR_END=$((CURRENT_YEAR + 1))
else
    SCHOOL_YEAR_START=$((CURRENT_YEAR - 1))
    SCHOOL_YEAR_END=$CURRENT_YEAR
fi
SYEAR=$SCHOOL_YEAR_END  # OpenSIS uses the end year as SYEAR
```

This ensures:
- The `school_years.start_date` and `end_date` always cover the current date
- The `schools.syear` matches the school year
- The `staff_school_relationship.syear` is correct

**Why this matters:** OpenSIS runs this query after login:
```sql
SELECT MAX(SYEAR) AS SYEAR FROM school_years
WHERE CURDATE() BETWEEN START_DATE AND END_DATE AND SCHOOL_ID=...
```
If today's date is outside the school year range, this query returns NULL and causes errors.

## Common Issues and Solutions

### Issue: Login redirects back to login page
**Cause**: Missing or incorrect database records
**Solution**: Verify all 5 required database records are correctly populated

### Issue: "DB Execute Failed" after login
**Cause**: Missing USER_ID column in staff table
**Solution**: Add the column and link it to the user

### Issue: Module navigation redirects to index.php
**Cause**: Missing profile_exceptions entries
**Solution**: Insert exact module names from Menu.php files

### Issue: Password verification fails
**Cause**: Using generic bcrypt hash instead of OpenSIS's hash function
**Solution**: Use GenerateNewHash() from PasswordHashFnc.php

## File Structure

```
/var/www/html/opensis/
├── Data.php              # Database credentials (created by setup)
├── DatabaseInc.php       # Database connection class
├── ConfigInc.php         # Main configuration includes
├── index.php             # Login page and main entry point
├── Modules.php           # Module loader (uses iframes)
├── Menu.php              # Menu builder
├── functions/
│   └── PasswordHashFnc.php  # Password hashing
├── modules/
│   ├── students/         # Student management
│   ├── attendance/       # Attendance tracking
│   ├── grades/           # Grade management
│   └── ...
└── install/
    └── OpensisSchemaMysqlInc.sql  # Database schema
```

## Verification Commands

```bash
# Check if login works
curl -c cookies.txt -d "USERNAME=admin&PASSWORD=admin123" http://localhost/opensis/index.php

# Query database
mysql -u opensis_user -p'opensis_password_123' opensis -e "SELECT * FROM students LIMIT 5;"

# Check Apache status
systemctl status apache2

# Check MariaDB status
systemctl status mariadb
```
