> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# WordPress Environment Notes

## Overview

WordPress CMS environment for content management tasks including creating blog posts, managing pages, uploading media, configuring settings, and managing users.

**Stack:** Ubuntu 22.04 + Apache 2.4 + PHP 8.2 + MariaDB (Docker) + WordPress 6.9

## Key Learnings

### 1. Docker-in-QEMU Pattern

WordPress requires a database. Instead of running MariaDB directly with systemd, we use Docker Compose inside the QEMU VM:

```yaml
# config/docker-compose.yml
services:
  mariadb:
    image: mariadb:10.11
    container_name: wordpress-mariadb
    environment:
      MYSQL_ROOT_PASSWORD: rootpass
      MYSQL_DATABASE: wordpress
      MYSQL_USER: wordpress
      MYSQL_PASSWORD: wordpresspass
    ports:
      - "3306:3306"
```

**Why Docker?**
- Cleaner service management
- Easy database queries via `docker exec`
- Consistent environment across restarts

### 2. WP-CLI Integration

WordPress CLI tool is essential for:
- Database configuration: `wp config create`
- Installation: `wp core install`
- Data import: `wp import`
- Queries: `wp db query`, `wp post list`, `wp user list`

Example utility function:
```bash
wp_cli() {
    cd /var/www/html/wordpress && wp "$@" --allow-root
}

wp_db_query() {
    docker exec wordpress-mariadb mysql -u wordpress -pwordpresspass wordpress -N -e "$1" 2>/dev/null
}
```

### 3. Auto-Login for Testing

To avoid login screen interactions, use a MU-plugin that auto-logs in the admin user:

```php
// wp-content/mu-plugins/auto-login.php
<?php
if (!is_user_logged_in() && !defined('DOING_CRON')) {
    $user = get_user_by('login', 'admin');
    if ($user) {
        wp_set_current_user($user->ID);
        wp_set_auth_cookie($user->ID, true);
    }
}
```

### 4. Theme Unit Test Data

Official WordPress test data provides realistic content:
- URL: https://raw.githubusercontent.com/WordPress/theme-test-data/master/themeunittestdata.wordpress.xml
- 186 items including posts, pages, comments, media
- Edge cases: special characters, nested categories, different post formats

**Import command:**
```bash
wp import /tmp/wordpress-theme-unit-test.xml --authors=create --allow-root
```

### 5. Permission Handling in Hooks

Hooks run as root but may have issues with /tmp permissions. Solution:

```bash
# Bad - may fail
echo "$VALUE" > /tmp/file.txt

# Good - handles permissions
echo "$VALUE" | sudo tee /tmp/file.txt > /dev/null
sudo chmod 666 /tmp/file.txt
```

### 6. Service Startup Timing

Wait for services with polling:

```bash
wait_for_wordpress() {
    local timeout=120
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if curl -s -o /dev/null -w "%{http_code}" http://localhost/ | grep -q "200\|302"; then
            return 0
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
    return 1
}
```

### 7. Screenshot Tool Availability

The base image may not have `scrot`. Use ImageMagick's `import` as fallback:

```bash
take_screenshot() {
    local path="${1:-/tmp/screenshot.png}"
    DISPLAY=:1 scrot "$path" 2>/dev/null || \
    DISPLAY=:1 import -window root "$path" 2>/dev/null || true
}
```

## Task Verification Pattern

### Two-Part Verification

1. **Export Script** (runs in container): Queries database and saves JSON to /tmp
2. **Verifier** (runs on host): Uses `copy_from_env` to read JSON, evaluates results

### Hybrid Scoring (70 programmatic + 30 VLM)

```python
# Programmatic checks (70 points max)
if result.get('post_found'):
    score += 15  # Post exists
if title_matches:
    score += 15  # Title correct
if status == 'publish':
    score += 10  # Status correct
if content_ok:
    score += 10  # Content present
if category_correct:
    score += 10  # Category assigned
if tags_correct:
    score += 10  # Tags assigned

# VLM checks (30 points max)
if vlm_available:
    # Check trajectory for correct workflow
    # Check final screenshot for success indicators
```

## Common Issues and Solutions

| Issue | Solution |
|-------|----------|
| Database connection fails | Wait for Docker container with polling |
| WordPress shows error | Check `docker logs wordpress-mariadb` |
| WP-CLI fails | Always use `--allow-root` flag |
| First-run wizard appears | Install MU-plugin to bypass |
| Categories not found | Use LOWER() for case-insensitive search |
| File permission denied | Use sudo tee pattern |

## Resource Requirements

- CPU: 4 cores (handles Apache + Docker + browser)
- RAM: 8GB (WordPress + MariaDB + Firefox)
- Network: Required for initial setup (Docker images, WP downloads)
- GPU: Not required

## Tasks Implemented

1. **create_blog_post**: Create a blog post with specific title, content, category, and tags
2. **edit_page**: Edit existing page title and content
3. **create_user**: Create new user with specific role

## Future Task Ideas

- Upload media files
- Install and configure plugins
- Change theme settings
- Create navigation menus
- Set up contact forms
- Configure permalinks
- Manage comments (approve/reply/delete)
- Schedule posts for future publication

## Verifier Design Lessons Learned

### Critical: Avoid Bypass Vulnerabilities

The initial verifiers had several issues that allowed tasks to pass without fully completing requirements:

1. **Tags/Categories**: Only checked if SOME tags were assigned, not ALL required tags
   - Fix: Require ALL expected tags, no partial credit

2. **Content Structure**: Only checked substring presence, not structural formatting
   - Fix: Validate heading tags (h2/h3/h4) and list items (li) in HTML

3. **Exact Match Requirements**: Gave partial credit for "close" values
   - Fix: Require exact match for critical fields (username, email)

4. **Pass Threshold**: Set too low at 60 points
   - Fix: Raise to 70 and add required boolean conditions

### Verifier Best Practices

```python
# BAD - Can bypass by just having keywords anywhere
if 'innovation' in content.lower():
    score += 5

# GOOD - Requires proper structure
if re.search(r'<li[^>]*>.*innovation.*</li>', content, re.IGNORECASE):
    score += 5

# BAD - Partial credit for wrong value
if 'marketing' in username.lower():
    score += 5  # Partial match

# GOOD - Exact match only
if username.strip().lower() == expected_username.strip().lower():
    score += 10

# BAD - Score-only pass criteria
passed = score >= 60

# GOOD - Score + required conditions
passed = score >= 70 and all_required_met
```

### Export Script Best Practices

Include actual content in JSON for structural validation:

```bash
# Include content for verifier to validate structure
ESCAPED_CONTENT=$(echo "$POST_CONTENT" | tr '\n' ' ' | sed 's/"/\\"/g' | head -c 5000)

# Include structural check results from shell
if echo "$CONTENT" | grep -qi '<h[2-4][^>]*>.*our values.*</h[2-4]>'; then
    HAS_HEADING="true"
fi
```
