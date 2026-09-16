> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenSIS Database Schema and Verification

## Database Overview

OpenSIS uses a MySQL/MariaDB database with approximately 100+ tables. This document covers the key tables relevant for gym_anything tasks.

## Key Tables for Task Verification

### 1. students
Primary table for student records.

```sql
DESCRIBE students;
-- Key columns:
-- student_id (PK, auto_increment)
-- first_name (varchar 50)
-- last_name (varchar 50)
-- middle_name
-- gender
-- birthdate
-- email
-- phone
```

**Verification Query:**
```sql
SELECT student_id, first_name, last_name, gender, birthdate, email 
FROM students 
WHERE first_name='Emily' AND last_name='Johnson';
```

### 2. student_enrollment
Links students to schools and tracks enrollment status.

```sql
DESCRIBE student_enrollment;
-- Key columns:
-- id (PK)
-- syear (school year)
-- school_id
-- student_id
-- grade_id
-- start_date
-- end_date
-- enrollment_code
```

**Verification Query:**
```sql
SELECT se.*, s.first_name, s.last_name 
FROM student_enrollment se
JOIN students s ON se.student_id = s.student_id
WHERE s.first_name='Emily' AND s.last_name='Johnson';
```

### 3. attendance_day
Daily attendance records.

```sql
-- Key columns:
-- student_id
-- school_date
-- attendance_code
-- period_id
```

**Verification Query:**
```sql
SELECT * FROM attendance_day 
WHERE student_id = (SELECT student_id FROM students WHERE first_name='Sample' AND last_name='Student')
AND school_date = CURDATE();
```

### 4. courses
Course definitions.

```sql
-- Key columns:
-- course_id (PK)
-- subject_id
-- course_title
-- school_id
-- syear
```

**Verification Query:**
```sql
SELECT * FROM courses 
WHERE course_title LIKE '%Chemistry%';
```

### 5. gradebook_grades
Individual grades for students.

```sql
-- Key columns:
-- student_id
-- course_period_id
-- assignment_id
-- points
```

## Authentication Tables

### login_authentication
User login credentials.

```sql
-- Key columns:
-- user_id (PK)
-- username
-- password (bcrypt hash)
-- profile_id (1=admin, 2=teacher, 3=student, 4=parent)
-- failed_login (lockout counter)
```

### staff
Staff/admin user details.

```sql
-- Key columns:
-- staff_id (PK)
-- current_school_id
-- first_name, last_name
-- profile ('admin', 'teacher')
-- profile_id
-- USER_ID (links to login_authentication.user_id)
```

### staff_school_info
Staff access permissions.

```sql
-- Key columns:
-- staff_id
-- opensis_access ('Y'/'N')
-- opensis_profile
```

### staff_school_relationship (CRITICAL!)
Links staff to schools - **MUST have a record or login fails!**

```sql
-- Key columns:
-- staff_id (PK)
-- school_id (PK)
-- syear (PK) - MUST match current school year!
```

**Why this is critical:** After login, OpenSIS queries:
```sql
SELECT ... FROM school_years WHERE ... AND SCHOOL_ID=<value_from_staff_school_relationship>
```
If no `staff_school_relationship` record exists, SCHOOL_ID is empty and the query fails!

**Verification Query:**
```sql
SELECT * FROM staff_school_relationship WHERE staff_id = 1;
-- Should return: staff_id=1, school_id=1, syear=<current_year>
```

### school_years (CRITICAL!)
Must have dates that cover the current date.

```sql
-- Key columns:
-- syear - school year (e.g., 2026)
-- start_date - must be BEFORE today
-- end_date - must be AFTER today
```

**Why this is critical:** OpenSIS queries:
```sql
SELECT MAX(SYEAR) FROM school_years WHERE CURDATE() BETWEEN START_DATE AND END_DATE
```
If today is outside the date range, this returns NULL and causes errors.

### profile_exceptions
Module-level permissions.

```sql
-- Key columns:
-- profile_id
-- modname (exact module path, e.g., 'students/Student.php')
-- can_use ('Y'/'N')
-- can_edit ('Y'/'N')
```

## Database Connection Details

```
Host: localhost
Database: opensis
Username: opensis_user
Password: opensis_password_123
```

## Verification Helper Script

A helper script is installed at `/usr/local/bin/opensis-db-query`:

```bash
#!/bin/bash
DB_USER="opensis_user"
DB_PASS="opensis_password_123"
DB_NAME="opensis"
mysql -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" -e "$1" 2>/dev/null
```

Usage:
```bash
opensis-db-query "SELECT * FROM students WHERE first_name='Emily'"
```

## Primary Verification Strategy

For gym_anything tasks, database queries provide the most reliable verification:

1. **Student Added**: Query students table for new record
2. **Attendance Recorded**: Query attendance_day for date and student
3. **Course Created**: Query courses table
4. **Grade Added**: Query gradebook_grades

VLM (screenshot) verification can be used as fallback when database verification is inconclusive.

## Quick Database Health Check

Run these queries to verify the database is correctly set up:

```sql
-- 1. Check admin user exists with correct profile
SELECT user_id, username, profile_id, failed_login
FROM login_authentication WHERE username='admin';
-- Expected: profile_id=1, failed_login=0

-- 2. Check staff record is linked
SELECT staff_id, current_school_id, USER_ID, profile_id
FROM staff WHERE staff_id=1;
-- Expected: USER_ID=1, profile_id=1

-- 3. Check staff_school_relationship EXISTS (CRITICAL!)
SELECT * FROM staff_school_relationship WHERE staff_id=1;
-- Expected: staff_id=1, school_id=1, syear=<current_year>
-- If EMPTY, login will fail with "DB Execute Failed"!

-- 4. Check school_years covers current date (CRITICAL!)
SELECT syear, start_date, end_date,
       CASE WHEN CURDATE() BETWEEN start_date AND end_date
            THEN 'OK' ELSE 'PROBLEM!' END as status
FROM school_years WHERE school_id=1;
-- Expected: status='OK'

-- 5. Check schools syear matches
SELECT id, syear, title FROM schools;
-- Expected: syear matches school_years.syear
```

## Fixing Common Database Issues

```bash
#!/bin/bash
# Quick fix script for database issues
YEAR=$(date +%Y)

mysql -u opensis_user -p'opensis_password_123' opensis << EOF
-- Fix staff_school_relationship
INSERT INTO staff_school_relationship (staff_id, school_id, syear)
VALUES (1, 1, $YEAR)
ON DUPLICATE KEY UPDATE syear=$YEAR;

-- Fix school_years dates
UPDATE school_years SET
    syear = $YEAR,
    start_date = CONCAT($YEAR - 1, '-08-01'),
    end_date = CONCAT($YEAR, '-06-30')
WHERE marking_period_id = 1;

-- Fix schools syear
UPDATE schools SET syear = $YEAR WHERE id = 1;

-- Fix login_authentication
UPDATE login_authentication SET profile_id = 1, failed_login = 0 WHERE username = 'admin';

-- Fix staff
ALTER TABLE staff ADD COLUMN IF NOT EXISTS USER_ID int(11) DEFAULT NULL;
UPDATE staff SET USER_ID = 1, profile_id = 1 WHERE staff_id = 1;
EOF

echo "Database fixes applied for year $YEAR"
```
