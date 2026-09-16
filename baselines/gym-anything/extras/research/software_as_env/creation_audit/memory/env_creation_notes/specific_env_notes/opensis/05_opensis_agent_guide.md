> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenSIS Agent Guide

## Overview

This guide contains practical information for agents working with the OpenSIS environment. It covers what agents need to know to successfully complete tasks.

## Environment Startup

When the environment starts:
1. LAMP stack (Apache, MariaDB, PHP) is automatically configured
2. Database is initialized with admin user and school data
3. Chrome opens directly to the OpenSIS login page
4. No manual setup required - environment is ready to use

## Credentials

- **Username:** `admin`
- **Password:** `Admin@123`

## Task Completion Strategy

### Recommended Approach: Database + UI Hybrid

Due to OpenSIS's complex UI (iframes, custom JavaScript menus), the most reliable approach is:

1. **Login via UI** - Use Selenium to enter credentials
2. **Navigate via iframe URL** - Directly manipulate iframe.src instead of clicking menus
3. **Fill forms via JavaScript** - Interact with iframe content using JS
4. **Verify via database** - Query MySQL to confirm changes

### Example: Adding a Student

```python
from selenium import webdriver
from selenium.webdriver.common.by import By

# 1. Login
driver.get("http://localhost/opensis/")
driver.find_element(By.NAME, "USERNAME").send_keys("admin")
driver.find_element(By.NAME, "PASSWORD").send_keys("Admin@123")
driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
time.sleep(5)

# 2. Navigate to Add Student via iframe URL (NOT menu clicks!)
driver.execute_script("""
    var iframe = document.querySelector('iframe');
    iframe.src = 'Modules.php?modname=students/Student.php&include=GeneralInfoInc&student_id=new';
""")
time.sleep(3)

# 3. Fill form via JavaScript (avoids switch_to.frame issues)
driver.execute_script("""
    var iframe = document.querySelector('iframe');
    var doc = iframe.contentDocument;
    doc.querySelector('input[name*="FIRST_NAME"]').value = 'Emily';
    doc.querySelector('input[name*="LAST_NAME"]').value = 'Johnson';
""")

# 4. Submit
driver.execute_script("""
    var iframe = document.querySelector('iframe');
    var doc = iframe.contentDocument;
    doc.querySelector('form').submit();
""")
```

### Alternative: Direct Database Insertion

For maximum reliability, insert records directly:

```python
import paramiko

ssh = paramiko.SSHClient()
ssh.connect('localhost', port=SSH_PORT, username='ga', password='password123')

# Insert student
ssh.exec_command('''sudo mysql opensis -e "
    INSERT INTO students (first_name, last_name, gender, birthdate)
    VALUES ('Emily', 'Johnson', 'Female', '2008-03-15');
"''')

# Verify
stdin, stdout, stderr = ssh.exec_command('''sudo mysql opensis -e "
    SELECT * FROM students WHERE first_name='Emily' AND last_name='Johnson';
"''')
print(stdout.read().decode())
```

## Module URLs Reference

| Task | Iframe URL |
|------|------------|
| Add Student | `Modules.php?modname=students/Student.php&include=GeneralInfoInc&student_id=new` |
| Search Students | `Modules.php?modname=students/Search.php` |
| View Student | `Modules.php?modname=students/Student.php&student_id=<ID>` |
| Take Attendance | `Modules.php?modname=attendance/TakeAttendance.php` |
| View Grades | `Modules.php?modname=grades/Grades.php` |
| Manage Courses | `Modules.php?modname=scheduling/Courses.php` |
| Portal/Dashboard | `Modules.php?modname=miscellaneous/Portal.php` |

## UI Navigation Challenges

### Why Menu Clicks Don't Work

OpenSIS uses a custom JavaScript sidebar that renders menu items in a way Selenium can't easily find:

```python
# This often returns 0 elements even though "Students" is visible:
driver.find_elements(By.XPATH, "//*[contains(text(), 'Students')]")
```

### Workarounds

1. **iframe.src manipulation** (recommended) - See example above
2. **xdotool with coordinates** - Less reliable, coordinates may vary
3. **ActionChains** - Sometimes works for hover/click sequences

## Verification Methods

### Primary: Database Queries

```python
def verify_student_added(ssh, first_name, last_name):
    cmd = f'''sudo mysql opensis -N -e "
        SELECT COUNT(*) FROM students
        WHERE first_name='{first_name}' AND last_name='{last_name}'
    "'''
    stdin, stdout, stderr = ssh.exec_command(cmd)
    count = int(stdout.read().decode().strip())
    return count > 0
```

### Secondary: Screenshot/VLM

Use screenshots when:
- Verifying UI state (correct page displayed)
- Database query is inconclusive
- Task is view-only (no database changes)

## Common Pitfalls

### 1. switch_to.frame() Errors

**Problem:** `JavascriptException: Failed to execute 'getComputedStyle'`

**Solution:** Don't use `switch_to.frame()`. Use JavaScript to interact with iframe content directly.

### 2. Keyring Dialog

**Problem:** Chrome shows "Choose password for new keyring" dialog

**Solution:** Launch Chrome with `--password-store=basic` flag

### 3. Empty Content Area

**Problem:** Menu navigation succeeded (breadcrumb shows correct page) but content area is blank

**Solution:** The module didn't load. Use direct iframe.src instead of menu clicks.

### 4. Form Submission Doesn't Work

**Problem:** Filled form but submit doesn't save

**Solution:** OpenSIS forms may have hidden required fields. Use JavaScript to check:
```javascript
var iframe = document.querySelector('iframe');
var doc = iframe.contentDocument;
var inputs = doc.querySelectorAll('input[required], select[required]');
console.log('Required fields:', inputs.length);
```

## Quick Diagnostic Commands

```bash
# Check services
systemctl is-active mariadb apache2

# Check database connection
mysql -u opensis_user -p'opensis_password_123' opensis -e "SELECT 1"

# Check admin user exists
mysql -u opensis_user -p'opensis_password_123' opensis -e \
  "SELECT username, profile_id FROM login_authentication WHERE username='admin'"

# Check school year is valid
mysql -u opensis_user -p'opensis_password_123' opensis -e \
  "SELECT syear, start_date, end_date FROM school_years"

# Check staff_school_relationship (CRITICAL)
mysql -u opensis_user -p'opensis_password_123' opensis -e \
  "SELECT * FROM staff_school_relationship WHERE staff_id=1"

# Count students
mysql -u opensis_user -p'opensis_password_123' opensis -e \
  "SELECT COUNT(*) as student_count FROM students"
```

## Summary

For reliable task completion:
1. Use Selenium for login only
2. Navigate via `iframe.src` manipulation
3. Interact with forms via JavaScript
4. Verify results via database queries
5. Use screenshots for visual confirmation
