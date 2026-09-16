> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenSIS Troubleshooting Guide

## Installation Approach

**Recommended**: Use the automated web installer (`automate_installer.py`) instead of manual database setup. The web installer properly handles:
- Password hashing
- Database relationships
- Required records
- Module permissions

Default credentials after automated installation:
- **Username**: admin
- **Password**: Admin@123

## Login Issues

### Problem: Login page shows but credentials don't work

**Symptoms:**
- Enter admin/Admin@123 (or admin/admin123 for manual setup)
- Page refreshes back to login
- No error message shown

**Root Causes & Solutions:**

1. **Wrong profile_id in login_authentication**
   ```sql
   -- Check current value
   SELECT profile_id FROM login_authentication WHERE username='admin';
   
   -- Fix: Must be 1, not 0
   UPDATE login_authentication SET profile_id = 1 WHERE username='admin';
   ```

2. **failed_login counter too high**
   ```sql
   -- Check current value
   SELECT failed_login FROM login_authentication WHERE username='admin';
   
   -- Fix: Reset to 0
   UPDATE login_authentication SET failed_login = 0 WHERE username='admin';
   ```

3. **Missing USER_ID in staff table**
   ```sql
   -- Check if column exists
   DESCRIBE staff;
   
   -- Add column if missing
   ALTER TABLE staff ADD COLUMN USER_ID int(11) DEFAULT NULL;
   
   -- Link to user
   UPDATE staff SET USER_ID = 1 WHERE staff_id = 1;
   ```

4. **Missing staff_school_info record**
   ```sql
   -- Check if exists
   SELECT * FROM staff_school_info WHERE staff_id = 1;
   
   -- Insert if missing
   INSERT INTO staff_school_info (staff_id, category, home_school, opensis_access)
   VALUES (1, 'Administrator', 1, 'Y');
   ```

5. **Wrong password hash**
   ```bash
   # Generate correct hash
   php -r 'include "/var/www/html/opensis/functions/PasswordHashFnc.php"; echo GenerateNewHash("admin123");'
   
   # Update in database
   mysql -u opensis_user -p'opensis_password_123' opensis -e \
     "UPDATE login_authentication SET password='<new_hash>' WHERE username='admin';"
   ```

### Problem: "DB Execute Failed" after login

**Symptoms:**
- Login succeeds (dashboard shows)
- Error message: "DB Execute Failed"
- SQL shows: `SELECT ... FROM school_years WHERE CURDATE() BETWEEN START_DATE AND END_DATE AND SCHOOL_ID=`
- Notice the SCHOOL_ID is empty!

**Root Causes (CRITICAL - check all three!):**

1. **Missing staff_school_relationship record** (MOST COMMON)
   ```sql
   -- Check if record exists
   SELECT * FROM staff_school_relationship WHERE staff_id = 1;

   -- If empty, insert it:
   INSERT INTO staff_school_relationship (staff_id, school_id, syear)
   VALUES (1, 1, 2026);  -- Use current year
   ```

2. **School year dates don't cover current date**
   ```sql
   -- Check current school year dates
   SELECT syear, start_date, end_date FROM school_years;

   -- If current date is outside the range, update:
   UPDATE school_years SET
       syear = 2026,
       start_date = '2025-08-01',
       end_date = '2026-06-30'
   WHERE marking_period_id = 1;

   -- Also update schools table
   UPDATE schools SET syear = 2026 WHERE id = 1;
   ```

3. **Missing USER_ID column in staff table**
   ```sql
   ALTER TABLE staff ADD COLUMN IF NOT EXISTS USER_ID int(11) DEFAULT NULL;
   UPDATE staff SET USER_ID = 1, profile_id = 1 WHERE staff_id = 1;
   ```

**IMPORTANT:** The `direct_db_setup.sh` script now handles all three automatically by:
- Calculating dynamic school year based on current date
- Creating staff_school_relationship record
- Ensuring USER_ID column exists

---

## Navigation Issues

### Problem: Module pages redirect to index.php

**Symptoms:**
- Click on menu item
- Redirected to home page
- URL shows index.php instead of Modules.php

**Root Causes & Solutions:**

1. **Missing profile_exceptions entries**
   ```sql
   -- Check current permissions
   SELECT * FROM profile_exceptions WHERE profile_id = 1;
   
   -- Add missing modules (must match EXACTLY what's in Menu.php)
   INSERT INTO profile_exceptions (profile_id, modname, can_use, can_edit)
   VALUES (1, 'students/Student.php', 'Y', 'Y');
   ```

2. **Session not maintained**
   - Make sure cookies are enabled in browser
   - Check if PHPSESSID cookie is being sent

3. **URL validation failure**
   - OpenSIS has strict URL validation in `validateQueryString()`
   - Avoid special characters in URLs
   - Use iframe.src changes instead of direct navigation

### Problem: Module content doesn't load in iframe

**Symptoms:**
- Menu appears
- Main content area is blank
- No JavaScript errors in console

**Solution:** Use JavaScript to change iframe src:
```javascript
var iframe = document.querySelector('iframe');
iframe.src = 'Modules.php?modname=students/Student.php';
```

---

## Database Issues

### Problem: "Access denied" for database user

**Solution:**
```sql
-- As root
CREATE USER IF NOT EXISTS 'opensis_user'@'localhost' IDENTIFIED BY 'opensis_password_123';
GRANT ALL PRIVILEGES ON opensis.* TO 'opensis_user'@'localhost';
FLUSH PRIVILEGES;
```

### Problem: Schema import fails

**Symptoms:**
- "Table already exists" errors
- Missing tables after import

**Solution:** These errors are often benign. Verify key tables exist:
```sql
SHOW TABLES LIKE 'students';
SHOW TABLES LIKE 'staff';
SHOW TABLES LIKE 'login_authentication';
```

### Problem: Data.php not found

**Symptoms:**
- "Database connection failed"
- Blank pages

**Solution:** Create Data.php:
```bash
cat > /var/www/html/opensis/Data.php << 'EOF'
<?php
$DatabaseType = 'mysqli';
$DatabaseServer = 'localhost';
$DatabaseUsername = 'opensis_user';
$DatabasePassword = 'opensis_password_123';
$DatabaseName = 'opensis';
$DatabasePort = '3306';
?>
EOF
chown www-data:www-data /var/www/html/opensis/Data.php
```

---

## Apache/PHP Issues

### Problem: Apache 500 errors

**Check logs:**
```bash
tail -f /var/log/apache2/error.log
```

**Common causes:**
- PHP syntax errors
- Missing PHP extensions
- Permission issues

### Problem: PHP pages show as plain text

**Solution:** Enable PHP module:
```bash
a2enmod php8.1
systemctl restart apache2
```

### Problem: Permission denied errors

**Solution:**
```bash
chown -R www-data:www-data /var/www/html/opensis
chmod -R 755 /var/www/html/opensis
```

---

## Chrome/Selenium Issues

### Problem: Chrome won't start

**Symptoms:**
- "Session not created" error
- Chrome crashes immediately

**Solution:**
```bash
# Kill existing Chrome processes
pkill -f chrome

# Start with required flags
google-chrome-stable \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --window-size=1920,1080 \
  --password-store=basic \
  http://localhost/opensis
```

### Problem: Keyring dialog appears

**Solution:** Use `--password-store=basic` flag when launching Chrome

### Problem: Can't interact with page elements

**Solution:**
- OpenSIS uses iframes - switch to iframe first in Selenium
- Or use JavaScript to manipulate iframe content

### Problem: Selenium can't find sidebar menu items

**Symptoms:**
- Menu items (Students, School Setup, etc.) are clearly visible in screenshot
- `driver.find_element(By.XPATH, "//*[contains(text(), 'Students')]")` returns 0 elements
- `find_element` timeout errors

**Root Cause:** OpenSIS sidebar uses custom JavaScript rendering. The menu text is rendered in a way that standard Selenium selectors can't reliably find.

**Solutions (in order of reliability):**

1. **Direct iframe URL manipulation (RECOMMENDED)**
   ```python
   # Instead of clicking menu, directly set iframe URL
   driver.execute_script("""
       var iframe = document.querySelector('iframe[name="body"]') || document.querySelector('iframe');
       if (iframe) {
           iframe.src = 'Modules.php?modname=students/Student.php&include=GeneralInfoInc&student_id=new';
       }
   """)
   ```

2. **Use xdotool with coordinates**
   ```bash
   # Click on Students menu (approximate coordinates)
   DISPLAY=:1 xdotool mousemove 130 379 click 1
   sleep 2
   # Click on submenu
   DISPLAY=:1 xdotool mousemove 94 457 click 1
   ```

3. **JavaScript click by text scanning**
   ```python
   driver.execute_script("""
       var allElements = document.querySelectorAll('a, li, span, div');
       for(var i=0; i<allElements.length; i++) {
           if(allElements[i].textContent.trim() === 'Students') {
               allElements[i].click();
               break;
           }
       }
   """)
   ```

### Problem: switch_to.frame() throws JavascriptException

**Symptoms:**
- Error: `Failed to execute 'getComputedStyle' on 'Window': parameter 1 is not of type 'Element'`

**Solution:** Avoid `switch_to.frame()` entirely. Use JavaScript to interact with iframe content:
```python
# Instead of switching to iframe, use JavaScript
driver.execute_script("""
    var iframe = document.querySelector('iframe');
    var doc = iframe.contentDocument;
    var firstName = doc.querySelector('input[name*="FIRST_NAME"]');
    if (firstName) firstName.value = 'Emily';
""")

---

## Verification Commands

```bash
# Check all services
systemctl status mariadb apache2

# Test database connection
mysql -u opensis_user -p'opensis_password_123' opensis -e "SELECT 1;"

# Check OpenSIS is accessible
curl -I http://localhost/opensis/

# Check PHP is working
php -r 'echo "PHP OK\n";'

# Check required PHP extensions
php -m | grep -E "mysqli|gd|curl|mbstring"

# View Apache error log
tail -20 /var/log/apache2/error.log

# Test login query
mysql -u opensis_user -p'opensis_password_123' opensis -e \
  "SELECT user_id, username, profile_id, failed_login FROM login_authentication;"

# Verify profile_exceptions
mysql -u opensis_user -p'opensis_password_123' opensis -e \
  "SELECT COUNT(*) FROM profile_exceptions WHERE profile_id=1;"
```

## Quick Fix Script

For common issues, run this diagnostic and fix script:

```bash
#!/bin/bash
echo "=== OpenSIS Quick Fix ==="

# Fix login_authentication
mysql -u opensis_user -p'opensis_password_123' opensis -e "
UPDATE login_authentication SET profile_id = 1, failed_login = 0 WHERE username = 'admin';
"

# Fix staff table
mysql -u opensis_user -p'opensis_password_123' opensis -e "
ALTER TABLE staff ADD COLUMN IF NOT EXISTS USER_ID int(11) DEFAULT NULL;
UPDATE staff SET USER_ID = 1, profile_id = 1 WHERE staff_id = 1;
"

# Ensure staff_school_info exists
mysql -u opensis_user -p'opensis_password_123' opensis -e "
INSERT INTO staff_school_info (staff_id, category, home_school, opensis_access)
VALUES (1, 'Administrator', 1, 'Y')
ON DUPLICATE KEY UPDATE opensis_access='Y';
"

echo "=== Fixes applied ==="
```
