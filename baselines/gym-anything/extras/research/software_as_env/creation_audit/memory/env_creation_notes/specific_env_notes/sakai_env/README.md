> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Sakai LMS Environment Notes

## Overview

Sakai is an open-source Learning Management System (LMS) by the Apereo Foundation for higher education. This environment runs Sakai 25.0 with MariaDB 10.6 on Ubuntu GNOME VM.

## Architecture

- **Database**: MariaDB 10.6 in Docker container (`sakai-db`)
- **Application**: Sakai 25.0 running natively on Tomcat 9.0.97 with Java 17 (Temurin)
- **Build**: Pre-built on host via Maven (`mvn install sakai:deploy`), artifacts mounted into VM
- **Resources**: 4 CPU, 8GB RAM (Sakai JVM uses 1-3GB heap)

## Critical Setup Quirks

### 1. Java 17 Module Opens (MOST CRITICAL)
Sakai 25 uses Apache Ignite for caching, which requires extensive `--add-opens` JVM flags:
```bash
--add-opens=java.base/java.lang=ALL-UNNAMED
--add-opens=java.base/java.nio=ALL-UNNAMED
--add-opens=java.base/sun.nio.ch=ALL-UNNAMED
--add-opens=java.base/java.net=ALL-UNNAMED
# ... and many more (see setenv.sh)
```
Without these, Ignite throws `InaccessibleObjectException` and the entire Sakai kernel fails to start.

### 2. JDBC URL Must Use `jdbc:mariadb://`
MariaDB JDBC driver 3.x uses `jdbc:mariadb://` not `jdbc:mysql://`:
```properties
# WRONG - MariaDB 3.x rejects this
url@javax.sql.DataSource=jdbc:mysql://127.0.0.1:3306/sakai
# CORRECT
url@javax.sql.DataSource=jdbc:mariadb://127.0.0.1:3306/sakai
```
Error: `Driver org.mariadb.jdbc.Driver claims to not accept jdbcUrl`

### 3. JreMemoryLeakPreventionListener Crashes
Must disable in `server.xml`:
```xml
<!-- <Listener className="org.apache.catalina.core.JreMemoryLeakPreventionListener" /> -->
```
The listener scans JDBC drivers via `DriverManager.getDrivers()`, which crashes with Sakai's 292 extra lib JARs.

### 4. Pre-Built Artifacts (Not Source Build in VM)
Building Sakai from source requires 2+ GB Maven heap and takes 15-30 min. The VM's 8GB RAM is insufficient for concurrent Sakai build + OS + Docker. Solution: build on host, mount artifacts.

Maven build on host (takes ~2 min with 4 threads and 755GB RAM):
```bash
mvn install sakai:deploy -Dmaven.test.skip=true -T 4C
```
Then copy `webapps/`, `components/`, and Sakai-specific `lib/` JARs to `sakai-deploy/`.

### 5. Shared Classloader Not Needed
Sakai's `SakaiApplicationContext` has its own classloader for `components/`. Do NOT set `shared.loader` in `catalina.properties` — leave it empty. The Sakai kernel JARs in `lib/` handle component loading.

### 6. Sakai-Specific Lib JARs
Only copy Sakai-ADDED JARs to `$CATALINA_HOME/lib/`, not duplicates of default Tomcat JARs. Compare the Maven-built Tomcat's lib against a fresh Tomcat to extract the 292 Sakai-specific additions.

### 7. First Boot Schema Creation
With `auto.ddl=true`, Sakai creates ~370 tables on first boot. This takes 3-6 minutes. Do NOT set `auto.ddl=false` prematurely — let the checkpoint system capture the state after successful boot.

### 8. Sakai Version Compatibility
| Sakai Version | Java Required | Tomcat |
|---------------|---------------|--------|
| 23.x (LTS) | Java 11 [11,12) | Tomcat 9 |
| 24.x | Java 17 | Tomcat 9 |
| 25.x | Java 17 | Tomcat 9 |

### 9. Demo Users
Setting `providerId=sample` in sakai.properties enables `SampleUserDirectoryProvider`:
- `admin` / `admin` (admin account)
- `instructor`, `instructor1`, `instructor2` / `sakai`
- `ta`, `ta1`, `ta2`, `ta3` / `sakai`
- `student0001`–`student0500` / `sakai`
- Any username starting with `test` / password = username

### 10. Login Form Interaction
The xlogin form (`/portal/xlogin`) uses `eid` and `pw` field names. For automated login, use a helper HTML file that auto-submits:
```html
<html><body onload='document.forms[0].submit()'>
<form method='post' action='http://localhost:8080/portal/xlogin'>
<input name='eid' value='admin'>
<input name='pw' value='admin'>
</form></body></html>
```
Place in `~/` (not `/tmp/`) for Snap Firefox access.

## Credentials

| Account | Username | Password |
|---------|----------|----------|
| Admin | admin | admin |
| Instructor | instructor | sakai |
| Students | student0001-student0500 | sakai |
| MariaDB root | root | rootpass |
| MariaDB app | sakai | sakaipass |

## Database Tables

Key tables for verification:
- `SAKAI_SITE` — Course sites (SITE_ID, TITLE, TYPE, PUBLISHED)
- `SAKAI_SITE_TOOL` — Tools per site (REGISTRATION = tool ID)
- `SAKAI_SITE_USER` — Site memberships
- `ASN_ASSIGNMENT` — Assignments (CONTEXT = site ID)
- `ANNOUNCEMENT_MESSAGE` — Announcements (CHANNEL_ID contains site ID)

## Real Data Sources

- **Syllabus**: MIT OCW 7.016 Introductory Biology (Fall 2018), CC BY-NC-SA 4.0
- **Course Schedule**: MIT OCW 7.016 lecture schedule
- **Research Paper Assignment**: Adapted from MIT OCW 20.109 (Spring 2010), CC BY-NC-SA 4.0

## Tasks

1. **create_course_site** — Create "CHEM 201: General Chemistry II" with tools
2. **create_assignment** — Create "Midterm Research Paper: Cell Biology" in BIO101
3. **post_announcement** — Post midterm study guide in HIST201
