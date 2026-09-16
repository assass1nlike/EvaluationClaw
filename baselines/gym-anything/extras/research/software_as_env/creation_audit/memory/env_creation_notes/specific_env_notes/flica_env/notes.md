> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Flight Crew View (FLICA) Environment Notes

## App Details
- **Package**: `com.robert.fcView`
- **App Name**: Flight Crew View
- **Platform**: Android (Google Play Store)
- **APK Type**: App Bundle (split APKs — base + 3 config splits)

## Account
- **Email**: `<configured at env-build time — see env-local secrets, do not commit>`
- **Password**: `<configured at env-build time — see env-local secrets, do not commit>`
- **Role**: Friend/Family (free tier, no airline credentials needed)
- **Display Name**: `<configured at env-build time>`

> The FLICA app requires a registered account. Provision one for the
> environment (Friend/Family tier is free) and inject the credentials via
> `env.json` `security.secrets_ref` or a task-side mount — never commit
> them to this notes file.

## App Flow (from fresh install)
1. Welcome screen: privacy checkbox + "Continue" button
2. Login/Create Account tabs with "Sign in with Google" and email/password fields
3. After login: "Are you the crewmember? Or are you a friend or family?" selection
4. If first time as Friend/Family: "Enter Your Name" dialog
5. Lands on **Friends** page (home screen for Friend/Family users)

## Available Screens (Friend/Family mode)
From the hamburger menu (top-right three lines):
1. **Notifications** — notification preferences
2. **Friends** — add/manage friends, share schedules (home screen)
3. **Crew Chat** — messaging feature
4. **Export to File** — export data
5. **Help/Contact Dev** — help and support
6. **Settings** — extensive settings with sections:
   - Profile photo, name, position
   - Flight Crew View Account
   - Subscription/Gift Codes
   - Airline Schedule Sync
   - Crew Assistant
   - Delay Watch
   - Nationality & Pilot Limits
   - Commuter Options
   - Weather
   - Home & Base Airports
   - Device Calendar Import/Export
   - Notifications
   - Personalization
   - Privacy

## Key Technical Notes
- App uses Firebase Auth — login state persists across `am force-stop` but is wiped by `pm clear`
- Split APK installation required (see android_env_creation_guide.md)
- Password contains `#` which needs `%23` encoding for `adb input text`
- The "crewmember or friend" screen only appears on first login; subsequent launches go straight to Friends
- Email verification is required once per account (server-side, persists across reinstalls)
