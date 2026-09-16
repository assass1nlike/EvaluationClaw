> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Virtualmin GPL Environment Notes

## Overview
- **Application**: Virtualmin GPL — web hosting control panel built on Webmin
- **Version**: Virtualmin 7.x / Webmin 2.621
- **OS**: Ubuntu 22.04 LTS (direct install, NOT Docker)
- **Port**: 10000 (HTTPS, self-signed cert)
- **Admin**: root / GymAnything123!
- **SSH**: ga / GymAnything123! (standard gym_anything password)

## Installation

### Pre-start (install_virtualmin.sh)
```bash
# Download official Virtualmin GPL installer
curl -o /home/ga/install.sh https://software.virtualmin.com/gpl/scripts/virtualmin-install.sh
chmod +x /home/ga/install.sh
# Run non-interactively in background (takes 10-20 min)
/home/ga/install.sh --minimal --force --hostname virtualmin.gym-anything.local \
    --bundle LEMP 2>&1 > /home/ga/virtualmin-install.log &
```

### Post-start (setup_virtualmin.sh)
1. Wait for installer to complete (marker file or `which virtualmin`)
2. Fix Webmin referrer checking (CRITICAL — see below)
3. Ensure services running: apache2, mariadb, named, postfix, dovecot, webmin
4. Bypass post-install wizard (`wizard_run=1` in `/etc/webmin/virtual-server/config`)
5. Run `virtualmin check-config`
6. Create 3 virtual servers: acmecorp.test, brightstar.test, greenvalley.test
7. Create email users and aliases for each domain
8. Import Sakila MySQL sample database
9. Download SpamAssassin corpus emails into Maildirs
10. Deploy Bootstrap HTML template to acmecorp.test webroot
11. Launch Firefox, dismiss SSL warning, log in

## CRITICAL: Webmin CSRF Protection

By default, Virtualmin 7.x installs with `referers_none=1` which BLOCKS all requests
with empty Referer headers (i.e., direct URL navigation from address bar in Firefox).

**Must fix BOTH files** (fixing only one is insufficient):
```bash
sed -i 's/^referers_none=1/referers_none=0/' /etc/webmin/config
grep -q "^referers_none=" /etc/webmin/config || echo "referers_none=0" >> /etc/webmin/config
sed -i 's/^referers_none=1/referers_none=0/' /etc/webmin/miniserv.conf
grep -q "^referers_none=" /etc/webmin/miniserv.conf || echo "referers_none=0" >> /etc/webmin/miniserv.conf
systemctl restart webmin
```

Webmin source logic: `if (!$gconfig{'referers_none'}) { $trust = 1; }` — only trusts
no-referer requests when `referers_none=0`.

## CRITICAL: Virtualmin 8.x URL Format

Virtualmin 8.x uses **numeric domain IDs** in URLs, NOT domain names.

**Wrong** (causes "Server no longer exists!" error):
```
https://localhost:10000/virtual-server/list_aliases.cgi?dom=brightstar.test
```

**Correct**:
```
https://localhost:10000/virtual-server/list_aliases.cgi?dom=177147490048564
```

Get domain ID dynamically:
```bash
virtualmin list-domains --domain acmecorp.test --id-only
```

## CRITICAL: Correct CGI Names

| Task | Correct URL | Notes |
|------|-------------|-------|
| Create Virtual Server | `/virtual-server/domain_form.cgi` | No query params needed |
| Create Email User | `/virtual-server/edit_user.cgi?dom=<ID>&new=1` | Uses domain ID |
| DNS Records | `/virtual-server/list_records.cgi?dom=<ID>` | NOT list_dns.cgi (doesn't exist) |
| MySQL Databases | `/virtual-server/list_databases.cgi?dom=<ID>` | NOT list_dbs.cgi (doesn't exist) |
| Email Aliases | `/virtual-server/list_aliases.cgi?dom=<ID>` | Uses domain ID |

## Login Coordinates (1920x1080)

```
Username field: xdotool mousemove 993 384 click 1   [VG 1280x720: 662, 256]
Tab to password field (more reliable than clicking password)
Sign In button:  xdotool mousemove 993 511 click 1   [VG 1280x720: 662, 341]
```

Use `--clearmodifiers` with xdotool type to avoid modifier key issues with `!` character:
```bash
xdotool type --clearmodifiers --delay 30 "GymAnything123!"
```

## SSL Warning Dismissal (1920x1080)

```
"Advanced..." button:            actual (1318, 705)
"Accept the Risk and Continue":  actual (1251, 1008)
```

## Pre-seeded Data

### Virtual Servers
| Domain | Admin Pass | User |
|--------|-----------|------|
| acmecorp.test | AcmePwd789! | acmecorp (unix) |
| brightstar.test | BrightPwd456! | brightstar (unix) |
| greenvalley.test | GreenPwd123! | greenvalley (unix) |

### Email Users
- acmecorp.test: admin, info, sales, support
- brightstar.test: admin, info, editor
- greenvalley.test: admin, orders

### Email Aliases (brightstar.test)
- abuse, hostmaster, postmaster, webmaster → brightstar@brightstar.test

### Databases
- acmecorp (MySQL — virtual server default)
- brightstar (MySQL — virtual server default)
- sakila (standalone — full Sakila sample DB: 1000 films, 200 actors, 599 customers)

### Email Content
- SpamAssassin public corpus (CC0) in Maildirs:
  - acmecorp/admin: 20 messages
  - acmecorp/info: 10 messages
  - brightstar/admin: 15 messages

### Website Content
- acmecorp.test: Bootstrap 5 Album template (`/home/acmecorp/public_html/index.html`)

## Services

| Service | Description | Check |
|---------|-------------|-------|
| webmin | Webmin/Virtualmin web UI | `systemctl is-active webmin` |
| apache2 | Web server for hosted sites | `systemctl is-active apache2` |
| mariadb | MySQL/MariaDB server | `systemctl is-active mariadb` |
| named | BIND DNS server | `systemctl is-active named` |
| postfix | SMTP mail server | `systemctl is-active postfix` |
| dovecot | IMAP/POP3 mail server | `systemctl is-active dovecot` |

## Virtualmin CLI Cheatsheet

```bash
# List domains
virtualmin list-domains --name-only

# Get domain ID
virtualmin list-domains --domain acmecorp.test --id-only

# Create domain
virtualmin create-domain --domain example.test --pass "Pass123!" \
    --unix --dir --webmin --web --dns --mail --mysql

# Create email user
virtualmin create-user --domain acmecorp.test --user john.smith \
    --pass "Pass123!" --real "John Smith"

# Delete email user
virtualmin delete-user --domain acmecorp.test --user john.smith

# List users for domain
virtualmin list-users --domain acmecorp.test

# Create email alias
virtualmin create-alias --domain brightstar.test --from support \
    --to admin@brightstar.test

# Delete alias
virtualmin delete-alias --domain brightstar.test --from support

# Get DNS records
virtualmin get-dns --domain acmecorp.test

# Modify DNS (add record)
virtualmin modify-dns --domain acmecorp.test \
    --add-record "blog CNAME acmecorp.test."
```

## Idempotency Pattern

The post_start script checks if ≥3 domains already exist (savevm state):
```bash
DOMAIN_COUNT=$(virtualmin list-domains --name-only | wc -l)
if [ "$DOMAIN_COUNT" -ge 3 ]; then
    # Fast path: just ensure services + referer fix + Firefox
    ...
    exit 0
fi
```

This allows fast recovery from savevm without re-running the full install.

## Common Issues and Fixes

### SSH Not Responding
- Use VNC to open GNOME Terminal (Activities → type "terminal")
- `gag` user has passwordless `sudo -i` for root access
- `systemctl restart ssh webmin`

### Firefox Shows SSL Warning on Every Launch
- Firefox snap doesn't persist SSL exceptions across VNC sessions
- `dismiss_ssl_warning()` called in `ensure_virtualmin_ready()` handles this

### Session Expiry During Navigation
- `ensure_virtualmin_ready()` checks window title for "Login" keyword
- If detected, calls `login_to_virtualmin()` automatically

### "Server no longer exists!" Error
- Using domain name in URL instead of numeric ID
- Fix: `DOMAIN_ID=$(virtualmin list-domains --domain NAME --id-only)`

### Module CGI Not Found (404)
- Using wrong CGI name (e.g., `list_dns.cgi` or `list_dbs.cgi`)
- Fix: use `list_records.cgi` for DNS, `list_databases.cgi` for MySQL

## Task Descriptions

### create_virtual_server
Create a new virtual server (hosted domain) named newclient.test with default features enabled.

### create_email_account
Create a new email account john.smith@acmecorp.test with appropriate settings.

### add_dns_record
Add a CNAME record for blog.acmecorp.test pointing to acmecorp.test.

### create_mysql_database
Create a new MySQL database named "shop" for brightstar.test.

### create_email_alias
Create an email alias support@brightstar.test forwarding to admin@brightstar.test.
