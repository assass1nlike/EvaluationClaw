> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# BlueMail Environment - Creation Notes

## Overview

BlueMail is an Electron-based email client for Linux. The environment sets up BlueMail with a local Dovecot IMAP server and Postfix SMTP server, populated with real emails from the SpamAssassin public corpus.

## Installation

- **Binary**: `/opt/BlueMail/bluemail` (installed from official .deb)
- **Download**: `https://download.bluemail.me/BlueMail/deb/BlueMail.deb`
- **Launch flag**: `--no-sandbox` required for running inside VM
- **Dependencies**: Standard Electron dependencies (libnss3, libgtk-3-0, libgbm1, etc.)

## Mail Server Configuration

### Dovecot IMAP

- **Ports**: 143 (plain) and 993 (plain text, NOT SSL)
- **Key insight**: BlueMail's port dropdown defaults to 993 and CANNOT be changed via xdotool. The dropdown is a custom React/Electron component that does not respond to synthetic mouse events, arrow keys, Tab, Space, or any other xdotool approach.
- **Solution**: Configure Dovecot with `ssl = no` globally and `ssl = no` on the `imaps` listener, so port 993 accepts plain text connections.
- **Auth**: `disable_plaintext_auth = no`, mechanisms: `plain login`
- **Mail format**: Maildir (`~/Maildir`)

### Postfix SMTP

- **Ports**: 25, 587 (submission), 465 (smtps) - all plain text, no TLS
- **BlueMail default SMTP port**: 587 (leave at default)
- **Config**: `smtpd_tls_security_level = none`, local-only delivery
- **master.cf**: Added submission and 465 entries with `smtpd_tls_security_level=none`

## First-Run Wizard Automation

The wizard has 9 steps, all automated via xdotool in a single bash session run as user `ga`.

### Critical Findings

1. **xdotool must run in a single bash session**: Individual SSH commands running xdotool do NOT register with BlueMail's Electron app. All xdotool commands must be in one script executed in one SSH session.

2. **Port dropdowns are immutable via xdotool**: Both IMAP and SMTP port dropdowns are custom Electron components. Tried: click, Down arrow, Tab+Down, Space, mousedown/mouseup - all failed. Solution: configure mail servers to accept connections on the default ports.

3. **Security dropdown works with Home+Return**: Unlike port dropdowns, the Security dropdown responds to xdotool `key Home` followed by `key Return` to select "None" (first item).

### Wizard Flow (720p coordinates)

| Step | Action | Coordinates |
|------|--------|-------------|
| 1. Welcome | Click "Continue" | (663, 399) |
| 2. Add Account | Click email field, type email | (663, 259) |
| 2b. | Click "Manual Setup" | (663, 400) |
| 3. Choose Provider | Click "Manual Setup" (bottom) | (663, 516) |
| 4. Manual Type | Click "IMAP" | (663, 291) |
| 5. IMAP Settings | Fill fields, Security=None | See below |
| 6. SMTP Settings | Fill server, Security=None, uncheck sign-in | See below |
| 7. Almost Done | Click "Next" | (663, 545) |
| 8. Customize | Click "Done" | (658, 544) |
| 9. Welcome Overlay | Click "No thanks" | (547, 501) |

### IMAP Settings Page Fields

| Field | Coordinates | Value |
|-------|-------------|-------|
| Email Address | (661, 290) | ga@example.com |
| Username | (661, 335) | ga |
| Password | (661, 380) | password123 |
| IMAP Server | (661, 425) | localhost |
| Security | (661, 470) | None (Home+Return) |
| Port | (728, 519) | 993 (leave default) |
| Next | (663, 559) | click |

### SMTP Settings Page Fields

| Field | Coordinates | Value |
|-------|-------------|-------|
| SMTP Server | (663, 367) | localhost |
| Security | (663, 413) | None (Home+Return) |
| Port | (732, 461) | 587 (leave default) |
| Require sign-in | (539, 488) | uncheck |
| Next | (663, 559) | click |

## Email Data

Uses the SpamAssassin public corpus:
- 50 ham emails in Inbox (`/workspace/assets/emails/ham/`)
- 20 spam emails in Junk (`/workspace/assets/emails/spam/`)
- Real email subjects include: "Re: New Sequences Window", "[SAdev] Interesting approach to Spam handling..", etc.

## Timing

- IMAP connection attempt: 30 second wait after clicking Next
- SMTP connection attempt: 20 second wait after clicking Next
- Window appearance: up to 45 seconds after launch
- Total wizard time: approximately 2-3 minutes

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port dropdown won't change | Configure server to accept on default port |
| xdotool clicks don't register | Must run in single bash session as user ga |
| Dovecot crash on port 993 | Use listener name "imaps" (not custom names) with `ssl = no` |
| BlueMail shows "Waiting for auth" | Normal with short nc timeout; login works fine |
| Welcome overlay blocks inbox | Click "No thanks" at (547, 501) |
